"""0005_usage: usage_records table

Revision ID: 0005_usage
Revises: 0004_tools_credentials
Create Date: 2026-10-25 21:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_usage"
down_revision: str | None = "0004_tools_credentials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usage_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.Text(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_micro_usd", sa.BigInteger(), nullable=False),
        sa.Column(
            "billed_cost_micro_usd",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("prompt_template_id", sa.Text(), nullable=False),
        sa.Column("prompt_template_version", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_usage_records_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["workflow_runs.id"],
            name=op.f("fk_usage_records_run_id_workflow_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["step_attempts.id"],
            name=op.f("fk_usage_records_attempt_id_step_attempts"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_records")),
        sa.CheckConstraint(
            "prompt_tokens >= 0",
            name="ck_usage_records_prompt_tokens_positive",
        ),
        sa.CheckConstraint(
            "completion_tokens >= 0",
            name="ck_usage_records_completion_tokens_positive",
        ),
        sa.CheckConstraint(
            "total_tokens >= 0",
            name="ck_usage_records_total_tokens_positive",
        ),
        sa.CheckConstraint(
            "estimated_cost_micro_usd >= 0",
            name="ck_usage_records_estimated_cost_positive",
        ),
        sa.CheckConstraint(
            "billed_cost_micro_usd >= 0",
            name="ck_usage_records_billed_cost_positive",
        ),
        sa.CheckConstraint(
            "outcome IN ('ok', 'invalid_output', 'provider_error', 'rate_limited')",
            name="ck_usage_records_outcome",
        ),
    )

    op.create_index(
        "ix_usage_records_org_created_at",
        "usage_records",
        ["org_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_usage_records_org_created_at", table_name="usage_records")
    op.drop_table("usage_records")
