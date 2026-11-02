"""Tenant-scoped persistence operations used by API routers."""

import hashlib
import json
import os
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.api.uploads import ValidatedUpload
from backend.app.core.config import settings
from backend.app.db.models import (
    AuditEvent,
    Document,
    ExternalSnapshot,
    ExternalSource,
    Factory,
    Job,
    JobDocument,
    RegulationUpdateProposal,
    Review,
    Tenant,
    User,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def get_user_by_email(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(User.email == email))


def get_job(session: Session, tenant_id: str, job_id: str) -> Job | None:
    return session.scalar(
        select(Job).where(Job.id == job_id, Job.tenant_id == tenant_id)
    )


def list_jobs(session: Session, tenant_id: str, limit: int = 100) -> Sequence[Job]:
    return session.scalars(
        select(Job)
        .where(Job.tenant_id == tenant_id)
        .order_by(Job.created_at.desc(), Job.id)
        .limit(limit)
    ).all()


def get_document(session: Session, tenant_id: str, document_id: str) -> Document | None:
    return session.scalar(
        select(Document)
        .join(JobDocument, JobDocument.document_id == Document.id)
        .where(
            Document.id == document_id,
            Document.tenant_id == tenant_id,
            JobDocument.tenant_id == tenant_id,
        )
    )


def get_job_documents(session: Session, tenant_id: str, job_id: str) -> list[Document]:
    return list(
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


def _storage_path(tenant_id: str, doc_hash: str) -> Path:
    root = settings.UPLOAD_DIRECTORY
    if not root.is_absolute():
        root = _PROJECT_ROOT / root
    return root / tenant_id / f"{doc_hash}.pdf"


def _persist_content(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    temporary_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary_path.write_bytes(content)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def create_or_get_job(
    session: Session,
    tenant_id: str,
    assessment_date: date,
    documents: list[ValidatedUpload],
    query: str = "Assess uploaded documents.",
) -> tuple[Job, bool]:
    hashes = sorted({document.doc_hash for document in documents})
    submission_hash = hashlib.sha256(
        json.dumps(hashes, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    existing = session.scalar(
        select(Job).where(
            Job.tenant_id == tenant_id,
            Job.submission_hash == submission_hash,
        )
    )
    if existing is not None:
        return existing, False

    try:
        with session.begin():
            job = Job(
                tenant_id=tenant_id,
                thread_id=str(uuid.uuid4()),
                status="queued",
                assessment_date=assessment_date.isoformat(),
                query=query,
                route="full_analysis",
                submission_hash=submission_hash,
            )
            session.add(job)
            session.flush()
            for upload in documents:
                document = session.scalar(
                    select(Document).where(
                        Document.tenant_id == tenant_id,
                        Document.doc_hash == upload.doc_hash,
                    )
                )
                if document is None:
                    storage_path = _storage_path(tenant_id, upload.doc_hash)
                    _persist_content(storage_path, upload.content)
                    document = Document(
                        tenant_id=tenant_id,
                        doc_hash=upload.doc_hash,
                        filename=upload.filename,
                        mime_type="application/pdf",
                        page_count=upload.page_count,
                        storage_path=str(storage_path),
                    )
                    session.add(document)
                    session.flush()
                session.add(
                    JobDocument(
                        job_id=job.id,
                        document_id=document.id,
                        tenant_id=tenant_id,
                    )
                )
            session.flush()
        return job, True
    except IntegrityError:
        session.rollback()
        concurrent_job = session.scalar(
            select(Job).where(
                Job.tenant_id == tenant_id,
                Job.submission_hash == submission_hash,
            )
        )
        if concurrent_job is None:
            raise
        return concurrent_job, False


def get_review(session: Session, tenant_id: str, review_id: str) -> Review | None:
    return session.scalar(
        select(Review).where(
            Review.id == review_id,
            Review.tenant_id == tenant_id,
        )
    )


def list_pending_reviews(
    session: Session, tenant_id: str, limit: int = 100
) -> list[tuple[Review, str]]:
    rows = session.execute(
        select(Review, Job.scorecard_data)
        .join(Job, Job.id == Review.job_id)
        .where(
            Review.tenant_id == tenant_id,
            Job.tenant_id == tenant_id,
            Review.status == "pending",
        )
        .order_by(Review.created_at, Review.id)
        .limit(limit)
    ).all()
    return [
        (review, _review_priority(scorecard_data))
        for review, scorecard_data in rows
    ]


def _review_priority(scorecard_data: dict[str, Any] | None) -> str:
    if scorecard_data is None:
        return "normal"
    escalation = scorecard_data.get("escalation")
    if isinstance(escalation, dict) and escalation.get("priority") == "critical":
        return "critical"
    return "normal"


def set_review_decision(
    session: Session,
    tenant_id: str,
    review_id: str,
    *,
    reviewer_id: str,
    decision: str,
    notes: str,
) -> Review | None:
    review = get_review(session, tenant_id, review_id)
    if review is None:
        return None
    if review.status != "pending":
        return review
    review.status = decision
    review.reviewer_id = reviewer_id
    review.decision = decision
    review.decision_notes = notes
    review.resolved_at = datetime.now(UTC)
    session.commit()
    session.refresh(review)
    return review


def list_factories(session: Session, tenant_id: str, limit: int = 100) -> Sequence[Factory]:
    return session.scalars(
        select(Factory)
        .where(Factory.tenant_id == tenant_id)
        .order_by(Factory.name, Factory.id)
        .limit(limit)
    ).all()


def get_factory(session: Session, tenant_id: str, factory_id: str) -> Factory | None:
    return session.scalar(
        select(Factory).where(
            Factory.id == factory_id,
            Factory.tenant_id == tenant_id,
        )
    )


def list_audit_events(
    session: Session,
    tenant_id: str,
    *,
    limit: int = 100,
) -> Sequence[AuditEvent]:
    return session.scalars(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == tenant_id)
        .order_by(AuditEvent.sequence.desc())
        .limit(limit)
    ).all()


def get_live_lookup_setting(session: Session, tenant_id: str) -> bool | None:
    return session.scalar(
        select(Tenant.live_lookup_enabled).where(Tenant.id == tenant_id)
    )


def set_live_lookup_setting(
    session: Session, tenant_id: str, enabled: bool
) -> bool | None:
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        return None
    tenant.live_lookup_enabled = enabled
    session.commit()
    session.refresh(tenant)
    return tenant.live_lookup_enabled


def list_pending_regulation_proposals(
    session: Session,
    tenant_id: str,
    limit: int = 100,
) -> Sequence[RegulationUpdateProposal]:
    return session.scalars(
        select(RegulationUpdateProposal)
        .where(
            RegulationUpdateProposal.tenant_id == tenant_id,
            RegulationUpdateProposal.status == "pending",
        )
        .order_by(RegulationUpdateProposal.detected_at.desc())
        .limit(limit)
    ).all()


def list_integration_status(
    session: Session,
    tenant_id: str,
) -> list[dict[str, Any]]:
    live_enabled = get_live_lookup_setting(session, tenant_id)
    if live_enabled is None:
        return []
    rows = session.execute(
        select(ExternalSource, func.max(ExternalSnapshot.fetched_at))
        .outerjoin(ExternalSnapshot, ExternalSnapshot.source_id == ExternalSource.id)
        .group_by(ExternalSource.id)
        .order_by(ExternalSource.id)
    ).all()
    return [
        {
            "source": source.id,
            "status": (
                "unverified"
                if live_enabled
                else ("snapshot_only" if as_of is not None else "unverified")
            ),
            "live_enabled": live_enabled,
            "as_of": as_of,
        }
        for source, as_of in rows
    ]
