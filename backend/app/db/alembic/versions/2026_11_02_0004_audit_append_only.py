"""Enforce audit-event immutability in the database.

Revision ID: 2026_11_02_0004
Revises: 2026_11_02_0003
"""

from collections.abc import Sequence

from alembic import op

revision: str = "2026_11_02_0004"
down_revision: str | None = "2026_11_02_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            CREATE FUNCTION reject_audit_event_mutation() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'audit_events is append-only';
            END;
            $$
            """
        )
        op.execute(
            """
            CREATE TRIGGER prevent_audit_events_mutation
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation()
            """
        )
    elif dialect == "sqlite":
        op.execute(
            """
            CREATE TRIGGER prevent_audit_events_update
            BEFORE UPDATE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'audit_events is append-only');
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER prevent_audit_events_delete
            BEFORE DELETE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'audit_events is append-only');
            END
            """
        )
    else:
        raise RuntimeError(f"Audit immutability is unsupported for database dialect: {dialect}")


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER prevent_audit_events_mutation ON audit_events")
        op.execute("DROP FUNCTION reject_audit_event_mutation()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER prevent_audit_events_update")
        op.execute("DROP TRIGGER prevent_audit_events_delete")
    else:
        raise RuntimeError(f"Audit immutability is unsupported for database dialect: {dialect}")
