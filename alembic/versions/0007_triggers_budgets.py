"""0007_triggers_budgets: triggers, budget_reservations, and workflow_runs FK

Revision ID: 0007_triggers_budgets
Revises: 0006_approvals_audit
Create Date: 2026-10-25 22:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_triggers_budgets"
down_revision: str | None = "0006_approvals_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. triggers table
    op.create_table(
        "triggers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("credential_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_triggers_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            name=op.f("fk_triggers_workflow_id_workflows"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["integration_credentials.id"],
            name=op.f("fk_triggers_credential_id_integration_credentials"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_triggers")),
        sa.CheckConstraint(
            "kind IN ('webhook')",
            name=op.f("ck_triggers_kind_valid"),
        ),
    )
    op.create_index(op.f("ix_triggers_org_id"), "triggers", ["org_id"], unique=False)
    op.create_index(op.f("ix_triggers_workflow_id"), "triggers", ["workflow_id"], unique=False)

    # 2. Add foreign key on workflow_runs.trigger_id -> triggers.id
    op.create_foreign_key(
        op.f("fk_workflow_runs_trigger_id_triggers"),
        "workflow_runs",
        "triggers",
        ["trigger_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 3. budget_reservations table
    op.create_table(
        "budget_reservations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.Text(), nullable=False),
        sa.Column("reserved_micro_usd", sa.BigInteger(), nullable=False),
        sa.Column("settled_micro_usd", sa.BigInteger(), nullable=True),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
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
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_budget_reservations_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["workflow_runs.id"],
            name=op.f("fk_budget_reservations_run_id_workflow_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_budget_reservations")),
        sa.UniqueConstraint("run_id", "step_id", name=op.f("uq_budget_reservations_run_step")),
        sa.CheckConstraint(
            "state IN ('RESERVED', 'SETTLED', 'RELEASED')",
            name=op.f("ck_budget_reservations_state_valid"),
        ),
        sa.CheckConstraint(
            "reserved_micro_usd >= 0",
            name=op.f("ck_budget_reservations_reserved_non_negative"),
        ),
    )
    op.create_index(
        op.f("ix_budget_reservations_org_id_state"),
        "budget_reservations",
        ["org_id", "state"],
        unique=False,
    )
    op.create_index(
        op.f("ix_budget_reservations_run_id"),
        "budget_reservations",
        ["run_id"],
        unique=False,
    )


def downgrade() -> None:
    # 3. Drop budget_reservations table
    op.drop_index(op.f("ix_budget_reservations_run_id"), table_name="budget_reservations")
    op.drop_index(op.f("ix_budget_reservations_org_id_state"), table_name="budget_reservations")
    op.drop_table("budget_reservations")

    # 2. Drop foreign key on workflow_runs.trigger_id
    op.drop_constraint(
        op.f("fk_workflow_runs_trigger_id_triggers"),
        "workflow_runs",
        type_="foreignkey",
    )

    # 1. Drop triggers table
    op.drop_index(op.f("ix_triggers_workflow_id"), table_name="triggers")
    op.drop_index(op.f("ix_triggers_org_id"), table_name="triggers")
    op.drop_table("triggers")
