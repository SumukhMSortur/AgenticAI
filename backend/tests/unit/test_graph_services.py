"""Unit coverage for tenant-scoped graph service assembly and fail-closed paths."""

import json
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.config import settings
from backend.app.db.models import (
    Base,
    Document,
    ExternalRecord,
    ExternalSnapshot,
    ExternalSource,
    Factory,
    Job,
    JobDocument,
    Tenant,
)
from backend.app.domain.models import (
    Claim,
    DocumentRef,
    ExtractedField,
    GraphState,
    RedactedPage,
    RiskForecast,
)
from backend.app.graph import services


@pytest.fixture
def graph_sessions(monkeypatch: pytest.MonkeyPatch) -> Any:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(services, "SessionLocal", factory)
    yield factory
    engine.dispose()


def _document_state(
    tenant_id: str,
    job_id: str,
    document: DocumentRef,
) -> GraphState:
    return {
        "tenant_id": tenant_id,
        "job_id": job_id,
        "documents": [document],
    }


def _add_document(
    graph_sessions: Any,
    *,
    tenant_id: str,
    job_id: str,
    document_id: str,
    storage_path: str,
) -> Document:
    with graph_sessions() as session:
        session.add(Tenant(id=tenant_id, name="Tenant"))
        session.add(
            Job(
                id=job_id,
                tenant_id=tenant_id,
                thread_id=str(uuid.uuid4()),
                status="pending",
                assessment_date="2026-11-02",
                query="Assess",
            )
        )
        document = Document(
            id=document_id,
            tenant_id=tenant_id,
            doc_hash="a" * 64,
            filename="certificate.pdf",
            storage_path=storage_path,
        )
        session.add(document)
        session.flush()
        session.add(
            JobDocument(job_id=job_id, document_id=document_id, tenant_id=tenant_id)
        )
        session.commit()
        return document


def test_documents_enforce_tenant_job_and_storage_boundaries(
    graph_sessions: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tenant_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    document_id = str(uuid.uuid4())
    tenant_root = tmp_path / "uploads" / tenant_id
    tenant_root.mkdir(parents=True)
    document_path = tenant_root / "certificate.pdf"
    document_path.write_bytes(b"pdf")
    monkeypatch.setattr(settings, "UPLOAD_DIRECTORY", tmp_path / "uploads")
    _add_document(
        graph_sessions,
        tenant_id=tenant_id,
        job_id=job_id,
        document_id=document_id,
        storage_path=str(document_path),
    )
    reference = DocumentRef(
        doc_id=document_id,
        doc_hash="a" * 64,
        filename="certificate.pdf",
        page_count=1,
    )
    state = _document_state(tenant_id, job_id, reference)

    assert services._documents(state) == [(reference, document_path)]
    with pytest.raises(ValueError, match="do not match"):
        services._documents(
            _document_state(
                tenant_id,
                job_id,
                reference.model_copy(update={"doc_hash": "b" * 64}),
            )
        )

    with graph_sessions() as session:
        stored = session.get(Document, document_id)
        assert stored is not None
        stored.storage_path = str(tmp_path / "outside.pdf")
        session.commit()
    with pytest.raises(PermissionError, match="outside the tenant"):
        services._documents(state)

    with graph_sessions() as session:
        stored = session.get(Document, document_id)
        assert stored is not None
        stored.storage_path = str(tenant_root / "missing.pdf")
        session.commit()
    with pytest.raises(FileNotFoundError, match="unavailable"):
        services._documents(state)


def test_redaction_and_extraction_stages_reject_empty_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    reference = DocumentRef(
        doc_id="doc-1",
        doc_hash="c" * 64,
        filename="certificate.pdf",
        page_count=1,
    )
    document_path = tmp_path / "certificate.pdf"
    monkeypatch.setattr(
        services,
        "_documents",
        lambda _state: [(reference, document_path)],
    )

    class Redactor:
        def redact_document(
            self, _path: Path, *, tenant_id: str, doc_id: str
        ) -> list[RedactedPage]:
            return [RedactedPage(page=1, doc_id=doc_id, redacted_text=tenant_id)]

    redacted = services._redact_stage(Redactor())({"tenant_id": "tenant-1"})
    assert redacted["redacted_pages"][0].redacted_text == "tenant-1"
    monkeypatch.setattr(services, "_documents", lambda _state: [])
    with pytest.raises(ValueError, match="No pages"):
        services._redact_stage(Redactor())({})

    extracted = ExtractedField(
        name="supplier_id",
        value="SUP-1",
        doc_id=reference.doc_id,
        doc_hash=reference.doc_hash,
        page=1,
        confidence=0.9,
    )

    class Extractor:
        def extract(self, _path: Path, _doc_id: str, _doc_hash: str) -> list[ExtractedField]:
            return [extracted]

    monkeypatch.setattr(
        services,
        "_documents",
        lambda _state: [(reference, document_path)],
    )
    result = services._extract_stage(Extractor())({})
    assert result["fields"] == [extracted]
    assert result["claims"][0].evidence_ids == ["extracted:doc-1:1:supplier_id"]
    assert result["evidence"][0].ref["doc_hash"] == reference.doc_hash

    class EmptyExtractor:
        def extract(self, _path: Path, _doc_id: str, _doc_hash: str) -> list[ExtractedField]:
            return []

    with pytest.raises(ValueError, match="No verifiable fields"):
        services._extract_stage(EmptyExtractor())({})


def test_latest_snapshots_and_identifier_extraction(graph_sessions: Any) -> None:
    fetched_at = datetime(2026, 11, 2, tzinfo=UTC)
    with graph_sessions() as session:
        source = ExternalSource(
            id="registry", name="Registry", terms_url="local", license="test"
        )
        session.add(source)
        session.flush()
        snapshot = ExternalSnapshot(
            source_id=source.id,
            fetched_at=fetched_at,
            content_hash="d" * 64,
            path="local.json",
        )
        session.add(snapshot)
        session.flush()
        session.add(
            ExternalRecord(
                snapshot_id=snapshot.id,
                key="REG-1",
                normalized_name="Supplier",
                country="BD",
                payload={"identifiers": {"registration": "FAC-1", "empty": None}},
            )
        )
        session.commit()

    snapshots = services._latest_snapshots()
    assert len(snapshots) == 1
    assert snapshots[0]["source"] == "registry"
    assert snapshots[0]["fetched_at"].tzinfo == UTC
    record = snapshots[0]["records"][0]
    assert services._record_identifier_values(record) == {"REG-1", "FAC-1"}
    assert services._record_identifier_values({"key": "plain"}) == {"plain"}


def test_enrichment_uses_exact_local_snapshots_and_records_provenance(
    graph_sessions: Any,
) -> None:
    tenant_id = str(uuid.uuid4())
    with graph_sessions() as session:
        session.add(Tenant(id=tenant_id, name="Tenant"))
        session.add(
            Factory(
                tenant_id=tenant_id,
                name="Factory",
                country="Bangladesh",
                external_id="FAC-1",
            )
        )
        facility_source = ExternalSource(
            id="facility-registry", name="Facilities", terms_url="local", license="test"
        )
        sanctions_source = ExternalSource(
            id="sanctions-watchlist", name="Watchlist", terms_url="local", license="test"
        )
        facility_snapshot = ExternalSnapshot(
            source=facility_source,
            fetched_at=datetime(2026, 11, 2, tzinfo=UTC),
            content_hash="e" * 64,
            path="facility.json",
        )
        sanctions_snapshot = ExternalSnapshot(
            source=sanctions_source,
            fetched_at=datetime(2026, 11, 2, tzinfo=UTC),
            content_hash="f" * 64,
            path="sanctions.json",
        )
        session.add_all(
            [
                facility_source,
                sanctions_source,
                facility_snapshot,
                sanctions_snapshot,
                ExternalRecord(
                    snapshot=facility_snapshot,
                    key="FAC-1",
                    normalized_name="Factory",
                    country="bangladesh",
                    payload={
                        "identifiers": {"facility": "FAC-1"},
                        "parent_company_match": True,
                    },
                ),
                ExternalRecord(
                    snapshot=sanctions_snapshot,
                    key="SUP-1",
                    normalized_name="Supplier",
                    country="BD",
                    payload={"identifiers": {"supplier": "SUP-1"}},
                ),
            ]
        )
        session.commit()

    fields = [
        ExtractedField(
            name="facility_id",
            value="FAC-1",
            doc_id="doc-1",
            doc_hash="1" * 64,
            page=1,
            confidence=0.9,
        ),
        ExtractedField(
            name="supplier_id",
            value="SUP-1",
            doc_id="doc-1",
            doc_hash="1" * 64,
            page=1,
            confidence=0.9,
        ),
        ExtractedField(
            name="scope_materials",
            value=["cotton", "linen"],
            doc_id="doc-1",
            doc_hash="1" * 64,
            page=1,
            confidence=0.9,
        ),
        ExtractedField(
            name="facility_id",
            value="FAC-2",
            doc_id="doc-2",
            doc_hash="2" * 64,
            page=1,
            confidence=0.9,
        ),
        ExtractedField(
            name="scope_materials",
            value="cotton",
            doc_id="doc-2",
            doc_hash="2" * 64,
            page=1,
            confidence=0.9,
        ),
    ]
    claims = [
        Claim(
            claim_id="claim-1",
            claim_text="Claim one",
            doc_id="doc-1",
            doc_hash="1" * 64,
            page=1,
            extractor_confidence=0.9,
        ),
        Claim(
            claim_id="claim-2",
            claim_text="Claim two",
            doc_id="doc-2",
            doc_hash="2" * 64,
            page=1,
            extractor_confidence=0.9,
        ),
    ]
    state: GraphState = {
        "tenant_id": tenant_id,
        "assessment_date": date(2026, 11, 2),
        "documents": [
            DocumentRef(
                doc_id="doc-1", doc_hash="1" * 64, filename="one.pdf", page_count=2
            ),
            DocumentRef(
                doc_id="doc-2", doc_hash="2" * 64, filename="two.pdf", page_count=1
            ),
        ],
        "fields": fields,
        "claims": claims,
        "redacted_pages": [
            RedactedPage(page=1, doc_id="doc-1", redacted_text="Page 1: certificate"),
            RedactedPage(page=1, doc_id="doc-2", redacted_text="No label"),
        ],
    }

    enriched = services._enrich_stage(state)
    context = enriched["verification_context"]
    lookup = context.external_lookups_by_claim["claim-1"]
    assert lookup.status == "healthy"
    assert lookup.matched is True
    assert lookup.country_match is True
    assert lookup.parent_company_match is True
    assert context.sanctions_matches_by_claim["claim-1"][0].matched is True
    assert context.external_lookups_by_claim["claim-2"].matched is False
    assert context.materials_by_doc == {"doc-1": ["cotton", "linen"], "doc-2": ["cotton"]}
    assert context.page_claims_by_doc == {"doc-1": ["Page 1: certificate"]}
    assert context.page_counts_by_doc == {"doc-1": 2, "doc-2": 1}
    assert {item.kind for item in enriched["evidence"]} == {
        "external_record",
        "watchlist_hit",
        "registry_entry",
    }


def test_enrichment_without_snapshots_reports_unavailable(
    graph_sessions: Any,
) -> None:
    tenant_id = str(uuid.uuid4())
    with graph_sessions() as session:
        session.add(Tenant(id=tenant_id, name="Tenant"))
        session.commit()

    claim = Claim(
        claim_id="claim-1",
        claim_text="Claim",
        doc_id="doc-1",
        doc_hash="1" * 64,
        page=1,
        extractor_confidence=0.9,
    )
    result = services._enrich_stage(
        {
            "tenant_id": tenant_id,
            "assessment_date": date(2026, 11, 2),
            "documents": [],
            "fields": [
                ExtractedField(
                    name="facility_id",
                    value="FAC-1",
                    doc_id="doc-1",
                    doc_hash="1" * 64,
                    page=1,
                    confidence=0.9,
                )
            ],
            "claims": [claim],
        }
    )
    context = result["verification_context"]
    assert context.external_lookups_by_claim["claim-1"].status == "unavailable"
    assert context.sanctions_matches_by_claim["claim-1"] is None
    assert result["evidence"] == []


def test_risk_forecast_escalates_when_data_is_unavailable_then_uses_approved_data(
    graph_sessions: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    no_facility = services._forecast_stage({"tenant_id": "tenant"})
    assert no_facility["escalation"].reason == "RISK_FORECAST_UNAVAILABLE"

    facility_field = ExtractedField(
        name="facility_id",
        value="FAC-1",
        doc_id="doc-1",
        doc_hash="1" * 64,
        page=1,
        confidence=0.9,
    )
    state: GraphState = {"tenant_id": "tenant-1", "fields": [facility_field]}
    unregistered = services._forecast_stage(state)
    assert unregistered["escalation"].details["reason"] == (
        "Facility is not registered to this tenant"
    )

    with graph_sessions() as session:
        session.add(Tenant(id="tenant-1", name="Tenant"))
        session.add(
            Factory(
                tenant_id="tenant-1",
                name="Factory",
                country="BD",
                external_id="FAC-1",
            )
        )
        session.commit()

    monkeypatch.setattr(services, "_synthetic_history_by_factory", lambda: {})
    no_history = services._forecast_stage(state)
    assert no_history["escalation"].details["reason"] == (
        "No approved local audit history is available"
    )
    forecast = RiskForecast(
        factory_id="factory-1",
        p_fail_6m=0.2,
        model_tag="xgboost",
    )

    class Inference:
        def predict(self, factory_id: str, history: list[dict[str, object]]) -> RiskForecast:
            assert factory_id
            assert history == [{"month": "2026-10"}]
            return forecast

    monkeypatch.setattr(services, "_synthetic_history_by_factory", lambda: {
        "FAC-1": [{"month": "2026-10"}]
    })
    monkeypatch.setattr(services, "_risk_inference", lambda: Inference())
    assert services._forecast_stage(state)["risk"] == forecast


def test_risk_artifacts_are_loaded_and_production_history_is_not_used(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path
    report_path = project_root / "reports" / "risk.json"
    report_path.parent.mkdir()
    report_path.write_text(
        json.dumps({"artifact": {"path": "models/risk.bin", "sha256": "abc"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(services, "_PROJECT_ROOT", project_root)
    monkeypatch.setattr(services, "_RISK_REPORT", report_path)
    loaded: list[tuple[Path, str]] = []

    class LoadedModel:
        pass

    def load_model(path: Path, checksum: str) -> LoadedModel:
        loaded.append((path, checksum))
        return model

    model = LoadedModel()
    monkeypatch.setattr(services.RiskInference, "load", load_model)
    services._risk_inference.cache_clear()
    assert services._risk_inference() is model
    assert loaded == [(project_root / "models" / "risk.bin", "abc")]
    services._risk_inference.cache_clear()

    history_path = tmp_path / "history.json"
    history_path.write_text(
        json.dumps(
            {
                "factories": [
                    {"factory_id": "FAC-1", "history": [{"month": "2026-10"}]},
                    {"factory_id": "FAC-2"},
                    "invalid",
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(services, "_RISK_HISTORY", history_path)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    services._synthetic_history_by_factory.cache_clear()
    assert services._synthetic_history_by_factory() == {}
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    services._synthetic_history_by_factory.cache_clear()
    assert services._synthetic_history_by_factory() == {
        "FAC-1": [{"month": "2026-10"}]
    }
    services._synthetic_history_by_factory.cache_clear()


def test_retrieval_and_workflow_assembly_keep_provider_selection_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class QueryService:
        def query(
            self, query: str, assessment_date: date, jurisdiction: str, limit: int
        ) -> tuple[bool, list[str]]:
            assert (query, assessment_date, jurisdiction, limit) == (
                "Check regulation",
                date(2026, 11, 2),
                "EU",
                5,
            )
            return True, ["passage-1"]

    monkeypatch.setattr(
        services, "get_regulation_query_service", lambda: QueryService()
    )
    retrieved = services._retrieve_stage(
        {"query": "Check regulation", "assessment_date": date(2026, 11, 2)}
    )
    assert retrieved["retrieved_context"] == [
        {"supported": True, "passages": ["passage-1"]}
    ]

    monkeypatch.setattr(settings, "LLM_PROVIDER", "remote")
    with pytest.raises(ValueError, match="only LLM_PROVIDER=fake"):
        services.create_workflow_services()

    monkeypatch.setattr(settings, "LLM_PROVIDER", "fake")
    monkeypatch.setattr(services.IntentRouter, "load", lambda: "router")
    monkeypatch.setattr(services, "DocumentRedactor", lambda: "redactor")
    monkeypatch.setattr(services, "HeuristicExtractor", lambda: "extractor")
    monkeypatch.setattr(services, "Verifier", lambda: "verifier")
    monkeypatch.setattr(services, "FakeLLM", lambda: "explainer")
    monkeypatch.setattr(services, "SqlAlchemyAuditRecorder", lambda _factory: "audit")
    workflow_services = services.create_workflow_services()
    assert workflow_services.router == "router"
    assert workflow_services.verifier == "verifier"
    assert workflow_services.explainer == "explainer"
    assert workflow_services.audit_recorder == "audit"
    assert callable(workflow_services.redact)
    assert callable(workflow_services.extract)
    assert callable(workflow_services.enrich)
    assert callable(workflow_services.forecast)
    assert callable(workflow_services.retrieve)
