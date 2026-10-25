"""0002_workflows: workflows, workflow_versions, immutability trigger

Revision ID: 0002_workflows
Revises: 0001_identity_orgs
Create Date: 2026-10-25 11:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0002_workflows"
down_revision: str | None = "0001_identity_orgs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. workflows table
    op.create_table(
        "workflows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_workflows_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_workflows_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflows")),
    )
    op.create_index(
        "ix_workflows_org_created_id",
        "workflows",
        ["org_id", sa.text("created_at DESC"), sa.text("id DESC")],
        unique=False,
    )
    op.create_index(op.f("ix_workflows_org_id"), "workflows", ["org_id"], unique=False)

    # 2. workflow_versions table
    op.create_table(
        "workflow_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("definition_json", JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_workflow_versions_version_positive")),
        sa.CheckConstraint(
            "status IN ('draft', 'published')", name=op.f("ck_workflow_versions_valid_status")
        ),
        sa.CheckConstraint(
            "(status != 'published') OR (checksum IS NOT NULL AND published_at IS NOT NULL)",
            name=op.f("ck_workflow_versions_published_version_requires_checksum"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_workflow_versions_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_workflow_versions_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            name=op.f("fk_workflow_versions_workflow_id_workflows"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_versions")),
        sa.UniqueConstraint(
            "workflow_id", "version", name=op.f("uq_workflow_versions_workflow_id_version")
        ),
    )
    op.create_index(
        "ix_workflow_versions_single_draft",
        "workflow_versions",
        ["workflow_id"],
        unique=True,
        postgresql_where=sa.text("status = 'draft'"),
    )
    op.create_index(
        op.f("ix_workflow_versions_workflow_id"), "workflow_versions", ["workflow_id"], unique=False
    )
    op.create_index(
        op.f("ix_workflow_versions_org_id"), "workflow_versions", ["org_id"], unique=False
    )

    # 3. Circular foreign key with deferred validation
    op.create_foreign_key(
        "fk_workflows_current_version_id_workflow_versions",
        "workflows",
        "workflow_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
        deferrable=True,
        initially="DEFERRED",
    )

    # 4. Immutability trigger for published workflow versions
    op.execute("""
    CREATE OR REPLACE FUNCTION forbid_published_version_change() RETURNS trigger AS $$
    BEGIN
      IF OLD.status = 'published' THEN
        RAISE EXCEPTION 'published workflow versions are immutable' USING ERRCODE = 'P0001';
      END IF;
      IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    """)

    op.execute("""
    CREATE TRIGGER trg_workflow_versions_immutable
      BEFORE UPDATE OR DELETE ON workflow_versions
      FOR EACH ROW EXECUTE FUNCTION forbid_published_version_change();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_workflow_versions_immutable ON workflow_versions;")
    op.execute("DROP FUNCTION IF EXISTS forbid_published_version_change();")
    op.drop_constraint(
        "fk_workflows_current_version_id_workflow_versions", "workflows", type_="foreignkey"
    )
    op.drop_table("workflow_versions")
    op.drop_table("workflows")
