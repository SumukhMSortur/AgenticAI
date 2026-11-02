"""Add tenant-scoped API submissions and lookup settings.

Revision ID: 2026_11_02_0003
Revises: 2026_11_02_0002
Create Date: 2026-11-02 16:30:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision: str = "2026_11_02_0003"
down_revision: str | None = "2026_11_02_0002"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "live_lookup_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column("tenants", "live_lookup_enabled", server_default=None)
    op.add_column("jobs", sa.Column("submission_hash", sa.String(64), nullable=True))
    op.add_column(
        "jobs",
        sa.Column(
            "query",
            sa.Text(),
            nullable=False,
            server_default="Assess uploaded documents.",
        ),
    )
    op.alter_column("jobs", "query", server_default=None)
    op.create_unique_constraint(
        "uq_jobs_tenant_submission_hash",
        "jobs",
        ["tenant_id", "submission_hash"],
    )
    op.create_unique_constraint(
        "uq_documents_tenant_doc_hash",
        "documents",
        ["tenant_id", "doc_hash"],
    )
    op.create_table(
        "job_documents",
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("job_id", "document_id"),
    )
    op.create_index("ix_job_documents_tenant_id", "job_documents", ["tenant_id"])
    op.add_column(
        "regulation_update_proposals",
        sa.Column("tenant_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "fk_regulation_update_proposals_tenant_id_tenants",
        "regulation_update_proposals",
        "tenants",
        ["tenant_id"],
        ["id"],
    )
    op.create_index(
        "ix_regulation_update_proposals_tenant_id",
        "regulation_update_proposals",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_regulation_update_proposals_tenant_id",
        table_name="regulation_update_proposals",
    )
    op.drop_constraint(
        "fk_regulation_update_proposals_tenant_id_tenants",
        "regulation_update_proposals",
        type_="foreignkey",
    )
    op.drop_column("regulation_update_proposals", "tenant_id")
    op.drop_index("ix_job_documents_tenant_id", table_name="job_documents")
    op.drop_table("job_documents")
    op.drop_constraint(
        "uq_documents_tenant_doc_hash",
        "documents",
        type_="unique",
    )
    op.drop_constraint(
        "uq_jobs_tenant_submission_hash",
        "jobs",
        type_="unique",
    )
    op.drop_column("jobs", "query")
    op.drop_column("jobs", "submission_hash")
    op.drop_column("tenants", "live_lookup_enabled")
