"""Append-only audit log with cryptographic hash chaining and tamper detection."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import AuditEvent

GENESIS_PREV_HASH = "0" * 64


def canonical_json(data: dict[str, Any]) -> str:
    """Produces a deterministic, sorted, whitespace-normalized JSON string for hashing."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def format_timestamp(ts: datetime) -> str:
    """Normalizes datetime to UTC ISO-8601 string across all database backends."""
    normalized = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)
    return normalized.isoformat()


def compute_event_hash(
    tenant_id: str,
    sequence: int,
    event_type: str,
    timestamp: datetime,
    prev_hash: str,
    doc_hash: str | None = None,
    regulation_version: str | None = None,
    model_version: str | None = None,
    prompt_version: str | None = None,
    verdicts: dict[str, Any] | None = None,
    reviewer_decision: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> str:
    """Computes a SHA-256 hash across all core event fields."""
    canonical_dict: dict[str, Any] = {
        "tenant_id": tenant_id,
        "sequence": sequence,
        "event_type": event_type,
        "timestamp": format_timestamp(timestamp),
        "prev_hash": prev_hash,
        "doc_hash": doc_hash or "",
        "regulation_version": regulation_version or "",
        "model_version": model_version or "",
        "prompt_version": prompt_version or "",
        "verdicts": verdicts or {},
        "reviewer_decision": reviewer_decision or {},
        "payload": payload or {},
    }
    encoded = canonical_json(canonical_dict).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def append_audit_event(
    db: Session,
    tenant_id: str,
    event_type: str,
    doc_hash: str | None = None,
    regulation_version: str | None = None,
    model_version: str | None = None,
    prompt_version: str | None = None,
    verdicts: dict[str, Any] | None = None,
    reviewer_decision: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
) -> AuditEvent:
    """Appends an immutable audit event to the tenant's hash chain."""
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.tenant_id == tenant_id)
        .order_by(AuditEvent.sequence.desc())
        .limit(1)
    )
    last_event = db.execute(stmt).scalar_one_or_none()

    if last_event is None:
        sequence = 1
        prev_hash = GENESIS_PREV_HASH
    else:
        sequence = last_event.sequence + 1
        prev_hash = last_event.event_hash

    event_time = timestamp or datetime.now(UTC)
    event_hash = compute_event_hash(
        tenant_id=tenant_id,
        sequence=sequence,
        event_type=event_type,
        timestamp=event_time,
        prev_hash=prev_hash,
        doc_hash=doc_hash,
        regulation_version=regulation_version,
        model_version=model_version,
        prompt_version=prompt_version,
        verdicts=verdicts,
        reviewer_decision=reviewer_decision,
        payload=payload,
    )

    event = AuditEvent(
        tenant_id=tenant_id,
        sequence=sequence,
        event_type=event_type,
        timestamp=event_time,
        doc_hash=doc_hash,
        regulation_version=regulation_version,
        model_version=model_version,
        prompt_version=prompt_version,
        verdicts=verdicts,
        reviewer_decision=reviewer_decision,
        payload=payload,
        prev_hash=prev_hash,
        event_hash=event_hash,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def verify_chain(db: Session, tenant_id: str) -> tuple[bool, str | None]:
    """Verifies the complete cryptographic chain of audit events for a tenant.

    Returns:
        (True, None) if completely valid.
        (False, error_reason) if tampering or inconsistency is detected.
    """
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.tenant_id == tenant_id)
        .order_by(AuditEvent.sequence.asc())
    )
    events = list(db.execute(stmt).scalars().all())

    if not events:
        return True, None

    expected_prev = GENESIS_PREV_HASH
    for idx, ev in enumerate(events):
        expected_seq = idx + 1
        if ev.sequence != expected_seq:
            return (
                False,
                f"Broken sequence at index {idx}: expected {expected_seq}, got {ev.sequence}",
            )

        if ev.prev_hash != expected_prev:
            return (
                False,
                f"Prev hash mismatch at sequence {ev.sequence}: expected {expected_prev}, got {ev.prev_hash}",
            )

        recalculated_hash = compute_event_hash(
            tenant_id=ev.tenant_id,
            sequence=ev.sequence,
            event_type=ev.event_type,
            timestamp=ev.timestamp,
            prev_hash=ev.prev_hash,
            doc_hash=ev.doc_hash,
            regulation_version=ev.regulation_version,
            model_version=ev.model_version,
            prompt_version=ev.prompt_version,
            verdicts=ev.verdicts,
            reviewer_decision=ev.reviewer_decision,
            payload=ev.payload,
        )
        if recalculated_hash != ev.event_hash:
            return (
                False,
                f"Payload tampering detected at sequence {ev.sequence}: expected hash {recalculated_hash}, stored {ev.event_hash}",
            )

        expected_prev = ev.event_hash

    return True, None
