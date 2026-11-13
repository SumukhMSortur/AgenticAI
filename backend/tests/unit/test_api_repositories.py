"""Tenant scoping and local evidence tests for API repository operations."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pymupdf
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.api.document_pages import render_pdf_page
from backend.app.api.repositories import (
    get_factory_risk,
    list_integration_status,
    reject_regulation_proposal,
)
from backend.app.db.audit_log import verify_chain
from backend.app.db.models import (
    Base,
    ExternalSnapshot,
    ExternalSource,
    Factory,
    Job,
    RegulationUpdateProposal,
    Tenant,
    User,
)


@pytest.fixture
def api_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_factory_risk_is_tenant_scoped_and_reads_latest_job(api_session: Session) -> None:
    tenant_id = str(uuid.uuid4())
    other_tenant_id = str(uuid.uuid4())
    factory_id = str(uuid.uuid4())
    tenant = Tenant(id=tenant_id, name="Tenant")
    other_tenant = Tenant(id=other_tenant_id, name="Other")
    factory = Factory(
        id=factory_id,
        tenant_id=tenant_id,
        name="Factory",
        country="Test",
        external_id="FACT-1",
    )
    job = Job(
        tenant_id=tenant_id,
        thread_id=str(uuid.uuid4()),
        status="completed",
        assessment_date="2026-11-02",
        query="Assess",
        route="full_analysis",
        scorecard_data={
            "risk_forecast": {
                "factory_id": "FACT-1",
                "p_fail_6m": 0.42,
                "model_tag": "xgboost",
                "baseline_comparison": {"status": "promoted"},
            }
        },
    )
    api_session.add_all([tenant, other_tenant, factory, job])
    api_session.commit()

    risk = get_factory_risk(api_session, tenant_id, factory_id)
    assert risk is not None
    assert risk["risk_score"] == 0.42
    assert risk["job_id"] == job.id
    assert get_factory_risk(api_session, other_tenant_id, factory_id) is None


def test_integration_status_reports_snapshot_freshness(api_session: Session) -> None:
    tenant_id = str(uuid.uuid4())
    api_session.add(Tenant(id=tenant_id, name="Tenant", live_lookup_enabled=False))
    api_session.add_all(
        [
            ExternalSource(
                id="fresh-source",
                name="Fresh source",
                terms_url="https://example.test/terms",
                license="fixture",
                max_age_days=30,
            ),
            ExternalSource(
                id="missing-source",
                name="Missing source",
                terms_url="https://example.test/terms",
                license="fixture",
            ),
        ]
    )
    api_session.flush()
    api_session.add(
        ExternalSnapshot(
            source_id="fresh-source",
            fetched_at=datetime.now(UTC) - timedelta(days=1),
            content_hash="a" * 64,
            record_count=3,
            path="fixtures/fresh.json",
        )
    )
    api_session.commit()

    status_by_source = {
        item["source"]: item for item in list_integration_status(api_session, tenant_id)
    }
    assert status_by_source["fresh-source"]["status"] == "snapshot_only"
    assert status_by_source["fresh-source"]["health"] == "healthy"
    assert status_by_source["fresh-source"]["record_count"] == 3
    assert status_by_source["missing-source"]["status"] == "disabled"
    assert status_by_source["missing-source"]["health"] == "unavailable"


def test_regulation_rejection_is_audited_for_the_tenant(api_session: Session) -> None:
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    proposal_id = str(uuid.uuid4())
    api_session.add(Tenant(id=tenant_id, name="Tenant"))
    api_session.flush()
    api_session.add(
        User(
            id=user_id,
            tenant_id=tenant_id,
            email="reviewer@example.test",
            hashed_password="test-hash",
            role="reviewer",
        )
    )
    proposal = RegulationUpdateProposal(
        id=proposal_id,
        tenant_id=tenant_id,
        source="fixture",
        candidate_version_id="version-1",
        status="pending",
    )
    api_session.add(proposal)
    api_session.commit()

    rejected = reject_regulation_proposal(
        api_session,
        tenant_id,
        proposal_id,
        reviewer_id=user_id,
        notes="Insufficient evidence",
    )

    assert rejected is proposal
    assert proposal.status == "rejected"
    assert proposal.reviewer_id == user_id
    assert verify_chain(api_session, tenant_id) == (True, None)

    with pytest.raises(ValueError, match="already been resolved"):
        reject_regulation_proposal(
            api_session,
            tenant_id,
            proposal_id,
            reviewer_id=user_id,
            notes="Duplicate decision",
        )


def test_pdf_page_rendering_enforces_tenant_path(tmp_path: Path) -> None:
    tenant_id = str(uuid.uuid4())
    tenant_dir = tmp_path / tenant_id
    tenant_dir.mkdir()
    pdf_path = tenant_dir / "document.pdf"
    document = pymupdf.open()
    document.new_page()
    document.save(pdf_path)
    document.close()

    png = render_pdf_page(str(pdf_path), tmp_path, tenant_id, 1)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")

    with pytest.raises(PermissionError, match="outside the tenant"):
        render_pdf_page(str(pdf_path), tmp_path, str(uuid.uuid4()), 1)
