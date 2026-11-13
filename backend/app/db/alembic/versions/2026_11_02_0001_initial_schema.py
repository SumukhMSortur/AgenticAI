"""Initial database schema for EcoChain Copilot.

Revision ID: 2026_11_02_0001
Revises: None
Create Date: 2026-11-02 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision: str = "2026_11_02_0001"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # 1. tenants
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 2. users
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # 3. factories
    op.create_table(
        "factories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("country", sa.String(100), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_factories_tenant_id", "factories", ["tenant_id"])
    op.create_index("ix_factories_external_id", "factories", ["external_id"])

    # 4. documents
    op.create_table(
        "documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("doc_hash", sa.String(64), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_documents_tenant_id", "documents", ["tenant_id"])
    op.create_index("ix_documents_doc_hash", "documents", ["doc_hash"])

    # 5. jobs
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("thread_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("assessment_date", sa.String(10), nullable=False),
        sa.Column("route", sa.String(50), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("scorecard_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_jobs_tenant_id", "jobs", ["tenant_id"])
    op.create_index("ix_jobs_thread_id", "jobs", ["thread_id"], unique=True)
    op.create_index("ix_jobs_status", "jobs", ["status"])

    # 6. reviews
    op.create_table(
        "reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("thread_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("reviewer_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decision", sa.String(50), nullable=True),
        sa.Column("decision_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_reviews_tenant_id", "reviews", ["tenant_id"])
    op.create_index("ix_reviews_job_id", "reviews", ["job_id"])
    op.create_index("ix_reviews_thread_id", "reviews", ["thread_id"])
    op.create_index("ix_reviews_status", "reviews", ["status"])

    # 7. audit_events
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("doc_hash", sa.String(64), nullable=True),
        sa.Column("regulation_version", sa.String(100), nullable=True),
        sa.Column("model_version", sa.String(100), nullable=True),
        sa.Column("prompt_version", sa.String(50), nullable=True),
        sa.Column("verdicts", sa.JSON(), nullable=True),
        sa.Column("reviewer_decision", sa.JSON(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("event_hash", sa.String(64), nullable=False),
    )
    op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"])
    op.create_index("ix_audit_events_sequence", "audit_events", ["sequence"])
    op.create_index("ix_audit_events_event_hash", "audit_events", ["event_hash"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("reviews")
    op.drop_table("jobs")
    op.drop_table("documents")
    op.drop_table("factories")
    op.drop_table("users")
    op.drop_table("tenants")
