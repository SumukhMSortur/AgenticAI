"""Local workflow service assembly with external calls disabled."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from sqlalchemy import select

from backend.app.core.config import settings
from backend.app.db.models import (
    Document,
    ExternalRecord,
    ExternalSnapshot,
    ExternalSource,
    Factory,
    JobDocument,
)
from backend.app.db.session import SessionLocal
from backend.app.domain.models import (
    Claim,
    DocumentRef,
    EscalationState,
    EvidenceItem,
    ExternalLookup,
    ExternalRef,
    ExtractedField,
    GraphState,
    RedactedPage,
    SanctionsMatch,
    VerificationContext,
)
from backend.app.extraction.heuristic import HeuristicExtractor
from backend.app.graph.workflow import SqlAlchemyAuditRecorder, WorkflowServices
from backend.app.llm.fake import FakeLLM
from backend.app.privacy.redactor import DocumentRedactor
from backend.app.rag.query_service import get_regulation_query_service
from backend.app.risk.inference import RiskInference
from backend.app.router.intent import IntentRouter
from backend.app.verifier.engine import Verifier

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_RISK_REPORT = _PROJECT_ROOT / "reports" / "risk.json"
_RISK_HISTORY = _PROJECT_ROOT / "data" / "synthetic" / "audit_histories_test.json"
_PAGE_LABEL = re.compile(r"\bpage\b", re.IGNORECASE)


def _upload_root() -> Path:
    root = settings.UPLOAD_DIRECTORY
    return (root if root.is_absolute() else _PROJECT_ROOT / root).resolve()


def _documents(state: GraphState) -> list[tuple[DocumentRef, Path]]:
    tenant_id = state["tenant_id"]
    job_id = state["job_id"]
    references = state.get("documents", [])
    with SessionLocal() as session:
        rows = list(
            session.scalars(
                select(Document)
                .join(JobDocument, JobDocument.document_id == Document.id)
                .where(
                    JobDocument.job_id == job_id,
                    JobDocument.tenant_id == tenant_id,
                    Document.tenant_id == tenant_id,
                )
                .order_by(Document.doc_hash)
            ).all()
        )
    expected = {reference.doc_id: reference.doc_hash for reference in references}
    actual = {document.id: document.doc_hash for document in rows}
    if not expected or actual != expected:
        raise ValueError("Job documents do not match tenant-scoped database records")

    tenant_root = (_upload_root() / tenant_id).resolve()
    documents: list[tuple[DocumentRef, Path]] = []
    reference_by_id = {reference.doc_id: reference for reference in references}
    for document in rows:
        path = Path(document.storage_path)
        if not path.is_absolute():
            path = _PROJECT_ROOT / path
        path = path.resolve()
        if not path.is_relative_to(tenant_root):
            raise PermissionError("Document storage path is outside the tenant upload directory")
        if not path.is_file():
            raise FileNotFoundError(f"Stored document is unavailable: {path.name}")
        documents.append((reference_by_id[document.id], path))
    return documents


def _redact_stage(
    redactor: DocumentRedactor,
) -> Callable[[GraphState], GraphState]:
    def redact(state: GraphState) -> GraphState:
        pages: list[RedactedPage] = []
        for reference, path in _documents(state):
            pages.extend(
                redactor.redact_document(
                    path,
                    tenant_id=state["tenant_id"],
                    doc_id=reference.doc_id,
                )
            )
        if not pages:
            raise ValueError("No pages were extracted from the uploaded documents")
        return {"redacted_pages": pages}

    return redact


def _extract_stage(
    extractor: HeuristicExtractor,
) -> Callable[[GraphState], GraphState]:
    def extract(state: GraphState) -> GraphState:
        fields: list[ExtractedField] = []
        claims: list[Claim] = []
        evidence: list[EvidenceItem] = []
        for reference, path in _documents(state):
            document_fields = extractor.extract(path, reference.doc_id, reference.doc_hash)
            if not document_fields:
                raise ValueError(f"No verifiable fields were extracted from {reference.doc_id}")
            fields.extend(document_fields)
            evidence_ids: list[str] = []
            for field in document_fields:
                evidence_id = f"extracted:{reference.doc_id}:{field.page}:{field.name}"
                evidence_ids.append(evidence_id)
                evidence.append(
                    EvidenceItem(
                        evidence_id=evidence_id,
                        kind="extracted_field",
                        ref={
                            "doc_id": field.doc_id,
                            "doc_hash": field.doc_hash,
                            "field": field.name,
                            "page": field.page,
                            "bbox": field.bbox.model_dump() if field.bbox else None,
                        },
                    )
                )
            claims.append(
                Claim(
                    claim_id=f"certificate:{reference.doc_id}",
                    claim_text="Submitted supplier certificate requires verification.",
                    doc_id=reference.doc_id,
                    doc_hash=reference.doc_hash,
                    page=1,
                    extractor_confidence=min(field.confidence for field in document_fields),
                    evidence_ids=evidence_ids,
                )
            )
        return {"fields": fields, "claims": claims, "evidence": evidence}

    return extract


def _latest_snapshots() -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    with SessionLocal() as session:
        sources = session.scalars(select(ExternalSource).order_by(ExternalSource.id)).all()
        for source in sources:
            snapshot = session.scalar(
                select(ExternalSnapshot)
                .where(ExternalSnapshot.source_id == source.id)
                .order_by(ExternalSnapshot.fetched_at.desc(), ExternalSnapshot.id)
                .limit(1)
            )
            if snapshot is None:
                continue
            fetched_at = snapshot.fetched_at
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=UTC)
            else:
                fetched_at = fetched_at.astimezone(UTC)
            records = session.scalars(
                select(ExternalRecord)
                .where(ExternalRecord.snapshot_id == snapshot.id)
                .order_by(ExternalRecord.key)
            ).all()
            snapshots.append(
                {
                    "source": source.id,
                    "fetched_at": fetched_at,
                    "snapshot_hash": snapshot.content_hash,
                    "records": [
                        {
                            "key": record.key,
                            "normalized_name": record.normalized_name,
                            "country": record.country,
                            "payload": record.payload,
                        }
                        for record in records
                    ],
                }
            )
    return snapshots


def _record_identifier_values(record: dict[str, Any]) -> set[str]:
    values = {str(record["key"])}
    payload = record.get("payload")
    identifiers = payload.get("identifiers") if isinstance(payload, dict) else None
    if isinstance(identifiers, dict):
        values.update(str(value) for value in identifiers.values() if value is not None)
    return values


def _enrich_stage(state: GraphState) -> GraphState:
    claims = state.get("claims", [])
    fields = state.get("fields", [])
    documents = state.get("documents", [])
    snapshots = _latest_snapshots()
    fields_by_doc: dict[str, dict[str, Any]] = {}
    for field in fields:
        fields_by_doc.setdefault(field.doc_id, {})[field.name] = field.value

    claims_by_doc: dict[str, list[str]] = {}
    fields_by_claim: dict[str, dict[str, Any]] = {}
    external_lookups: dict[str, ExternalLookup] = {}
    sanctions: dict[str, list[SanctionsMatch] | None] = {}
    external_evidence: list[EvidenceItem] = []
    for claim in claims:
        claims_by_doc.setdefault(claim.doc_id, []).append(claim.claim_id)
        values = fields_by_doc.get(claim.doc_id, {})
        fields_by_claim[claim.claim_id] = values
        identifiers = {
            value
            for value in (values.get("facility_id"), values.get("supplier_id"))
            if isinstance(value, str) and value
        }

        sanctions_sources = [
            snapshot
            for snapshot in snapshots
            if any(
                marker in str(snapshot["source"]).casefold()
                for marker in ("sanction", "watchlist", "ofac", "fsf")
            )
        ]
        if not sanctions_sources:
            sanctions[claim.claim_id] = None
        else:
            claim_sanctions: list[SanctionsMatch] = []
            sanctions[claim.claim_id] = claim_sanctions
            for snapshot in sanctions_sources:
                matching_records = [
                    record
                    for record in snapshot["records"]
                    if identifiers & _record_identifier_values(record)
                ]
                record = matching_records[0] if matching_records else None
                evidence_id = (
                    f"sanctions:{claim.claim_id}:{snapshot['source']}:"
                    f"{str(snapshot['snapshot_hash'])[:16]}"
                )
                fetched_at = snapshot["fetched_at"]
                record_key = str(record["key"]) if record is not None else "snapshot"
                external_evidence.append(
                    EvidenceItem(
                        evidence_id=evidence_id,
                        kind="watchlist_hit" if record is not None else "registry_entry",
                        ref=ExternalRef(
                            source=str(snapshot["source"]),
                            fetched_at=fetched_at,
                            snapshot_hash=str(snapshot["snapshot_hash"]),
                            record_key=record_key,
                        ).model_dump(mode="json"),
                    )
                )
                claim_sanctions.append(
                    SanctionsMatch(
                        source=str(snapshot["source"]),
                        matched=record is not None,
                        match_type="exact_id" if record is not None else "none",
                        score=1.0 if record is not None else 0.0,
                        record_key=str(record["key"]) if record is not None else None,
                        snapshot_hash=str(snapshot["snapshot_hash"]),
                        fetched_at=fetched_at,
                        evidence_id=evidence_id,
                    )
                )

        facility_id = values.get("facility_id")
        if not isinstance(facility_id, str) or not facility_id:
            continue

        selected_snapshot: dict[str, Any] | None = None
        matched_record: dict[str, Any] | None = None
        for snapshot in snapshots:
            for record in snapshot["records"]:
                if facility_id in _record_identifier_values(record):
                    selected_snapshot = snapshot
                    matched_record = record
                    break
            if matched_record is not None:
                break
        if selected_snapshot is None and snapshots:
            selected_snapshot = snapshots[0]

        if selected_snapshot is None:
            external_lookups[claim.claim_id] = ExternalLookup(
                source="local-snapshot",
                status="unavailable",
                matched=False,
                match_type="none",
                score=0.0,
                details={"reason": "No verified local facility snapshot is configured"},
            )
            continue

        source_id = str(selected_snapshot["source"])
        snapshot_hash = str(selected_snapshot["snapshot_hash"])
        fetched_at = selected_snapshot["fetched_at"]
        record_key = str(matched_record["key"]) if matched_record is not None else "snapshot"
        evidence_id = f"facility:{claim.claim_id}:{source_id}:{snapshot_hash[:16]}"
        external_evidence.append(
            EvidenceItem(
                evidence_id=evidence_id,
                kind="external_record",
                ref=ExternalRef(
                    source=source_id,
                    fetched_at=fetched_at,
                    snapshot_hash=snapshot_hash,
                    record_key=record_key,
                ).model_dump(mode="json"),
            )
        )
        factory_country = None
        with SessionLocal() as session:
            factory = session.scalar(
                select(Factory).where(
                    Factory.tenant_id == state["tenant_id"],
                    Factory.external_id == facility_id,
                )
            )
            if factory is not None:
                factory_country = factory.country
        matched_payload = matched_record.get("payload") if matched_record is not None else None
        parent_company_match = (
            matched_payload.get("parent_company_match")
            if isinstance(matched_payload, dict)
            and isinstance(matched_payload.get("parent_company_match"), bool)
            else None
        )
        record_country = matched_record.get("country") if matched_record is not None else None
        country_match = (
            factory_country.casefold() == record_country.casefold()
            if isinstance(factory_country, str) and isinstance(record_country, str)
            else None
        )
        external_lookups[claim.claim_id] = ExternalLookup(
            source=source_id,
            status="healthy",
            matched=matched_record is not None,
            match_type="exact_id" if matched_record is not None else "none",
            score=1.0 if matched_record is not None else 0.0,
            record_key=str(matched_record["key"]) if matched_record is not None else None,
            fetched_at=fetched_at,
            snapshot_hash=snapshot_hash,
            country_match=country_match,
            parent_company_match=parent_company_match,
            evidence_id=evidence_id,
            details={"match_method": "exact_identifier"},
        )

    page_claims: dict[str, list[str]] = {}
    for page in state.get("redacted_pages", []):
        if _PAGE_LABEL.search(page.redacted_text):
            page_claims.setdefault(page.doc_id, []).append(page.redacted_text)

    page_counts = {document.doc_id: document.page_count for document in documents}
    supplier_ids = {
        doc_id: value["supplier_id"]
        for doc_id, value in fields_by_doc.items()
        if isinstance(value.get("supplier_id"), str)
    }
    facility_ids = {
        doc_id: value["facility_id"]
        for doc_id, value in fields_by_doc.items()
        if isinstance(value.get("facility_id"), str)
    }
    materials = {
        doc_id: value["scope_materials"]
        if isinstance(value["scope_materials"], list)
        else [value["scope_materials"]]
        for doc_id, value in fields_by_doc.items()
        if isinstance(value.get("scope_materials"), (str, list))
    }
    # If no separate BOM document was uploaded, map bom_doc_by_claim to the certificate doc
    # so that single-certificate submissions verify scope against the certificate scope
    bom_docs = {claim.claim_id: claim.doc_id for claim in claims}

    context = VerificationContext(
        assessment_date=state["assessment_date"],
        fields_by_claim=fields_by_claim,
        page_claims_by_doc=page_claims,
        page_counts_by_doc=page_counts,
        materials_by_doc=materials,
        supplier_ids_by_doc=supplier_ids,
        facility_ids_by_doc=facility_ids,
        certificate_doc_by_claim={claim.claim_id: claim.doc_id for claim in claims},
        bom_doc_by_claim=bom_docs,
        external_lookups_by_claim=external_lookups,
        sanctions_matches_by_claim=sanctions,
        risk_score=None,
    )
    return {"evidence": external_evidence, "verification_context": context}


@lru_cache(maxsize=1)
def _risk_inference() -> RiskInference:
    report = json.loads(_RISK_REPORT.read_text(encoding="utf-8"))
    artifact = report["artifact"]
    relative_path = Path(str(artifact["path"]).replace("\\", "/"))
    return RiskInference.load(
        _PROJECT_ROOT / relative_path,
        str(artifact["sha256"]),
    )


@lru_cache(maxsize=1)
def _synthetic_history_by_factory() -> dict[str, list[dict[str, object]]]:
    if settings.ENVIRONMENT == "production":
        return {}
    payload = json.loads(_RISK_HISTORY.read_text(encoding="utf-8"))
    factories = payload.get("factories", [])
    return {
        str(factory["factory_id"]): cast(list[dict[str, object]], factory["history"])
        for factory in factories
        if isinstance(factory, dict) and "factory_id" in factory and "history" in factory
    }


def _forecast_stage(state: GraphState) -> GraphState:
    facility_ids = [
        field.value
        for field in state.get("fields", [])
        if field.name == "facility_id" and isinstance(field.value, str)
    ]
    if not facility_ids:
        return {
            "risk": None,
            "escalation": EscalationState(
                is_escalated=True,
                priority="normal",
                reason="RISK_FORECAST_UNAVAILABLE",
                details={"reason": "No facility ID was extracted"},
            ),
        }

    external_id = facility_ids[0]
    with SessionLocal() as session:
        factory = session.scalar(
            select(Factory).where(
                Factory.tenant_id == state["tenant_id"],
                Factory.external_id == external_id,
            )
        )
        if factory is None:
            return {
                "risk": None,
                "escalation": EscalationState(
                    is_escalated=True,
                    priority="normal",
                    reason="RISK_FORECAST_UNAVAILABLE",
                    details={"reason": "Facility is not registered to this tenant"},
                ),
            }
        history = _synthetic_history_by_factory().get(external_id)
        if history is None:
            return {
                "risk": None,
                "escalation": EscalationState(
                    is_escalated=True,
                    priority="normal",
                    reason="RISK_FORECAST_UNAVAILABLE",
                    details={"reason": "No approved local audit history is available"},
                ),
            }
        forecast = _risk_inference().predict(factory.id, history)
    return {"risk": forecast}


def _retrieve_stage(state: GraphState) -> GraphState:
    service = get_regulation_query_service()
    supported, passages = service.query(
        state["query"],
        state["assessment_date"],
        "EU",
        5,
    )
    return {
        "retrieved_context": [
            {
                "supported": supported,
                "passages": passages,
            }
        ]
    }


def create_workflow_services() -> WorkflowServices:
    """Assemble local processing services and the explicitly selected fake explainer."""
    if settings.LLM_PROVIDER != "fake":
        raise ValueError("This workflow assembly supports only LLM_PROVIDER=fake")
    return WorkflowServices(
        router=IntentRouter.load(),
        redact=_redact_stage(DocumentRedactor()),
        extract=_extract_stage(HeuristicExtractor()),
        enrich=_enrich_stage,
        forecast=_forecast_stage,
        retrieve=_retrieve_stage,
        verifier=Verifier(),
        explainer=FakeLLM(),
        audit_recorder=SqlAlchemyAuditRecorder(SessionLocal),
    )
