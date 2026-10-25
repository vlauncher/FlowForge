"""0004_tools_credentials: integration_credentials, tool_effects

Revision ID: 0004_tools_credentials
Revises: 0003_runs_outbox
Create Date: 2026-10-25 16:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, BYTEA, JSONB

from alembic import op

revision: str = "0004_tools_credentials"
down_revision: str | None = "0003_runs_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. integration_credentials table
    op.create_table(
        "integration_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("encrypted_secret", BYTEA(), nullable=False),
        sa.Column("key_id", sa.String(length=50), nullable=False),
        sa.Column(
            "allowed_hosts",
            ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "permission_scopes",
            ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_integration_credentials_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integration_credentials")),
        sa.UniqueConstraint("org_id", "name", name=op.f("uq_integration_credentials_org_name")),
    )
    op.create_index(
        op.f("ix_integration_credentials_org_id"),
        "integration_credentials",
        ["org_id"],
        unique=False,
    )
    op.create_index(
        "ix_integration_credentials_org_provider",
        "integration_credentials",
        ["org_id", "provider"],
        unique=False,
    )

    # 2. tool_effects table
    op.create_table(
        "tool_effects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("external_ref", sa.String(length=255), nullable=True),
        sa.Column("response_summary", JSONB(astext_type=sa.Text()), nullable=True),
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
        sa.CheckConstraint(
            "state IN ('INTENDED', 'COMMITTED', 'FAILED', 'AMBIGUOUS')",
            name=op.f("ck_tool_effects_state"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_tool_effects_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["workflow_runs.id"],
            name=op.f("fk_tool_effects_run_id_workflow_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tool_effects")),
        sa.UniqueConstraint(
            "provider", "idempotency_key", name=op.f("uq_tool_effects_provider_idempotency")
        ),
    )
    op.create_index(op.f("ix_tool_effects_org_id"), "tool_effects", ["org_id"], unique=False)
    op.create_index(op.f("ix_tool_effects_run_id"), "tool_effects", ["run_id"], unique=False)
    op.create_index("ix_tool_effects_run_step", "tool_effects", ["run_id", "step_id"], unique=False)


def downgrade() -> None:
    op.drop_table("tool_effects")
    op.drop_table("integration_credentials")
