"""Add organizations, profiles, memberships, invitations and RLS policies.

Revision ID: 2026_11_16_0005
Revises: 2026_11_02_0004
"""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "2026_11_16_0005"
down_revision: str | None = "2026_11_02_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name

    # 1. Organizations
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("region", sa.String(50), nullable=False, server_default="eu-west"),
        sa.Column("strict_boundary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"])

    # 2. Profiles (linked to auth.users in Supabase or local user IDs)
    op.create_table(
        "profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("avatar_url", sa.String(500), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_profiles_email", "profiles", ["email"])

    # 3. Memberships (RBAC roles: owner, admin, reviewer, analyst, viewer)
    op.create_table(
        "memberships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, server_default="viewer"),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("invited_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "org_id", name="uq_memberships_user_org"),
    )
    op.create_index("ix_memberships_org_role", "memberships", ["org_id", "role"])

    # 4. Invitations
    op.create_table(
        "invitations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, server_default="viewer"),
        sa.Column("token_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_invitations_org_email", "invitations", ["org_id", "email"])

    # 5. Enable Row Level Security (RLS) on PostgreSQL
    if dialect == "postgresql":
        # Enable RLS on organizations and related business tables
        tables = [
            "organizations",
            "factories",
            "documents",
            "jobs",
            "job_documents",
            "reviews",
            "audit_events",
        ]
        for tbl in tables:
            op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY;")
            # Policy allows access if app.current_org_id matches org_id or tenant_id, or if empty (for superuser/system)
            target_col = "tenant_id" if tbl in ["factories", "documents", "jobs", "job_documents", "reviews", "audit_events"] else "id"
            op.execute(
                f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_policies WHERE tablename = '{tbl}' AND policyname = '{tbl}_org_isolation'
                    ) THEN
                        CREATE POLICY {tbl}_org_isolation ON {tbl}
                        FOR ALL
                        USING (
                            NULLIF(current_setting('app.current_org_id', true), '') IS NULL
                            OR {target_col}::text = current_setting('app.current_org_id', true)
                        );
                    END IF;
                END $$;
                """
            )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        tables = ["organizations", "factories", "documents", "jobs", "job_documents", "reviews", "audit_events"]
        for tbl in tables:
            op.execute(f"DROP POLICY IF EXISTS {tbl}_org_isolation ON {tbl};")
            op.execute(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY;")

    op.drop_table("invitations")
    op.drop_table("memberships")
    op.drop_table("profiles")
    op.drop_table("organizations")
