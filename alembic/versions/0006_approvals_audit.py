"""0006_approvals_audit: approval_requests, audit_events, and immutability trigger

Revision ID: 0006_approvals_audit
Revises: 0005_usage
Create Date: 2026-10-25 21:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0006_approvals_audit"
down_revision: str | None = "0005_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. approval_requests table
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.Text(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_role", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("summary", JSONB(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_comment", sa.String(length=1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_approval_requests_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["workflow_runs.id"],
            name=op.f("fk_approval_requests_run_id_workflow_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["workflow_versions.id"],
            name=op.f("fk_approval_requests_version_id_workflow_versions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"],
            ["users.id"],
            name=op.f("fk_approval_requests_decided_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_requests")),
        sa.CheckConstraint(
            "assigned_role IN ('reviewer', 'admin', 'owner')",
            name="ck_approval_requests_assigned_role",
        ),
        sa.CheckConstraint(
            "state IN ('PENDING', 'APPROVED', 'REJECTED', 'EXPIRED', 'CANCELLED')",
            name="ck_approval_requests_state",
        ),
        sa.CheckConstraint(
            "(state NOT IN ('APPROVED', 'REJECTED')) OR (decided_by IS NOT NULL AND decided_at IS NOT NULL)",
            name="ck_approval_requests_decided_contract",
        ),
    )

    op.create_index(
        "ix_approval_requests_org_state_expires",
        "approval_requests",
        ["org_id", "state", "expires_at"],
    )
    op.create_index(
        "uq_approval_requests_pending_run_step",
        "approval_requests",
        ["run_id", "step_id"],
        unique=True,
        postgresql_where=sa.text("state = 'PENDING'"),
    )

    # 2. audit_events table
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column(
            "redacted_metadata",
            JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_audit_events_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_audit_events_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
        sa.CheckConstraint(
            "actor_type IN ('user', 'system', 'webhook')",
            name="ck_audit_events_actor_type",
        ),
    )

    op.create_index(
        "ix_audit_events_org_created_at",
        "audit_events",
        ["org_id", sa.text("created_at DESC")],
    )

    # 3. Append-only trigger on audit_events
    op.execute("""
        CREATE FUNCTION forbid_audit_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only' USING ERRCODE = 'P0002';
        END; $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER trg_audit_events_immutable BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION forbid_audit_mutation();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_events_immutable ON audit_events;")
    op.execute("DROP FUNCTION IF EXISTS forbid_audit_mutation();")
    op.drop_index("ix_audit_events_org_created_at", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("uq_approval_requests_pending_run_step", table_name="approval_requests")
    op.drop_index("ix_approval_requests_org_state_expires", table_name="approval_requests")
    op.drop_table("approval_requests")
