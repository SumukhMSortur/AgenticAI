"""Unit tests for cryptographic audit log hash chain and tamper detection."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.errors import AuditChainTamperError
from backend.app.db.audit_log import append_audit_event, verify_chain
from backend.app.db.models import AuditEvent, Base, Tenant


@pytest.fixture
def db_session() -> Session:
    """Provides an isolated in-memory SQLite database session with all tables."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TRIGGER prevent_audit_events_update
            BEFORE UPDATE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'audit_events is append-only');
            END
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TRIGGER prevent_audit_events_delete
            BEFORE DELETE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'audit_events is append-only');
            END
            """
        )
    session_factory = sessionmaker(bind=engine)
    session = session_factory()

    tenant = Tenant(id="tenant_test", name="Test Apparel Brand")
    session.add(tenant)
    session.commit()

    try:
        yield session
    finally:
        session.close()


def test_audit_chain_sequential_integrity(db_session: Session) -> None:
    """Verifies events append sequentially with valid prev_hash chaining."""
    e1 = append_audit_event(
        db=db_session,
        tenant_id="tenant_test",
        event_type="document_ingest",
        doc_hash="sha256_mock_1",
        payload={"filename": "gots_cert.pdf"},
    )
    assert e1.sequence == 1
    assert e1.prev_hash == "0" * 64

    e2 = append_audit_event(
        db=db_session,
        tenant_id="tenant_test",
        event_type="verification",
        doc_hash="sha256_mock_1",
        verdicts={"V-EXP-001": "pass"},
    )
    assert e2.sequence == 2
    assert e2.prev_hash == e1.event_hash

    is_valid, reason = verify_chain(db_session, "tenant_test")
    assert is_valid is True
    assert reason is None


def test_audit_event_immutability_orm_enforcement(db_session: Session) -> None:
    """Attempting to update or delete an AuditEvent at ORM level must raise AuditChainTamperError."""
    ev = append_audit_event(
        db=db_session,
        tenant_id="tenant_test",
        event_type="ingest",
        doc_hash="doc_hash_1",
    )

    # Attempt update
    ev.event_type = "tampered_type"
    with pytest.raises(AuditChainTamperError) as exc_update:
        db_session.commit()
    assert "strictly append-only" in str(exc_update.value)

    db_session.rollback()

    # Attempt delete
    fresh_ev = db_session.get(AuditEvent, ev.id)
    assert fresh_ev is not None
    db_session.delete(fresh_ev)
    with pytest.raises(AuditChainTamperError) as exc_delete:
        db_session.commit()
    assert "strictly append-only" in str(exc_delete.value)


def test_audit_chain_tamper_detection_on_raw_sql_tamper(db_session: Session) -> None:
    """If an attacker modifies rows directly via raw SQL, verify_chain must detect it."""
    append_audit_event(
        db=db_session,
        tenant_id="tenant_test",
        event_type="event_1",
        doc_hash="hash_1",
        payload={"field": "original_val"},
    )
    append_audit_event(
        db=db_session,
        tenant_id="tenant_test",
        event_type="event_2",
        doc_hash="hash_2",
        payload={"field": "val_2"},
    )

    # Initial chain must be valid
    is_valid, _ = verify_chain(db_session, "tenant_test")
    assert is_valid is True

    # Even raw SQL must be rejected by the database trigger.
    with pytest.raises(DBAPIError, match="audit_events is append-only"):
        db_session.execute(
            text(
                "UPDATE audit_events SET payload = "
                '\'{"field": "tampered_val"}\' WHERE sequence = 1'
            )
        )
    db_session.rollback()

    # Simulate a privileged actor disabling the trigger; the hash chain still detects edits.
    db_session.execute(text("DROP TRIGGER prevent_audit_events_update"))
    db_session.execute(
        text(
            "UPDATE audit_events SET payload = "
            '\'{"field": "tampered_val"}\' WHERE sequence = 1'
        )
    )
    db_session.commit()

    # verify_chain must detect tampering
    is_valid, reason = verify_chain(db_session, "tenant_test")
    assert is_valid is False
    assert reason is not None
    assert "Payload tampering detected" in reason
