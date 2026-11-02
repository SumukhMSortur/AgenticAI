"""Add external data and regulation proposals tables (Addendum A - R1).

Revision ID: 2026_11_02_0002
Revises: 2026_11_02_0001
Create Date: 2026-11-02 10:35:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_11_02_0002"
down_revision: str | None = "2026_11_02_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. external_sources
    op.create_table(
        "external_sources",
        sa.Column("id", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("terms_url", sa.String(length=500), nullable=False),
        sa.Column("license", sa.String(length=100), nullable=False),
        sa.Column("max_age_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # 2. external_snapshots
    op.create_table(
        "external_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=50), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("path", sa.String(length=500), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["external_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_external_snapshots_source_id", "external_snapshots", ["source_id"])
    op.create_index("ix_external_snapshots_content_hash", "external_snapshots", ["content_hash"])

    # 3. external_records
    op.create_table(
        "external_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=150), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("country", sa.String(length=100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["external_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_external_records_snapshot_id", "external_records", ["snapshot_id"])
    op.create_index("ix_external_records_key", "external_records", ["key"])
    op.create_index("ix_external_records_normalized_name", "external_records", ["normalized_name"])
    op.create_index("ix_external_records_country", "external_records", ["country"])

    # 4. watchlist_hits
    op.create_table(
        "watchlist_hits",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=50), nullable=False),
        sa.Column("record_key", sa.String(length=150), nullable=False),
        sa.Column("match_type", sa.String(length=50), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_watchlist_hits_job_id", "watchlist_hits", ["job_id"])
    op.create_index("ix_watchlist_hits_source_id", "watchlist_hits", ["source_id"])

    # 5. regulation_update_proposals
    op.create_table(
        "regulation_update_proposals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidate_version_id", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("reviewer_id", sa.String(length=36), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_regulation_update_proposals_candidate_version_id",
        "regulation_update_proposals",
        ["candidate_version_id"],
    )
    op.create_index(
        "ix_regulation_update_proposals_status",
        "regulation_update_proposals",
        ["status"],
    )


def downgrade() -> None:
    op.drop_table("regulation_update_proposals")
    op.drop_table("watchlist_hits")
    op.drop_table("external_records")
    op.drop_table("external_snapshots")
    op.drop_table("external_sources")
