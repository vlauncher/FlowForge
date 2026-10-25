"""Database models for integration credentials and tool effect ledgers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, BYTEA, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import new_id
from app.infrastructure.db.base import Base

if TYPE_CHECKING:
    from app.modules.executions.models import WorkflowRun


class IntegrationCredential(Base):
    """Encrypted write-only integration credentials scoped to an organization."""

    __tablename__ = "integration_credentials"
    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_integration_credentials_org_name"),
        Index("ix_integration_credentials_org_provider", "org_id", "provider"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    encrypted_secret: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    key_id: Mapped[str] = mapped_column(String(50), nullable=False)
    allowed_hosts: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        default=list,
        nullable=False,
    )
    permission_scopes: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        default=list,
        nullable=False,
    )
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )


class ToolEffect(Base):
    """Idempotency and side-effect ledger for external tools."""

    __tablename__ = "tool_effects"
    __table_args__ = (
        CheckConstraint(
            "state IN ('INTENDED', 'COMMITTED', 'FAILED', 'AMBIGUOUS')",
            name="ck_tool_effects_state",
        ),
        UniqueConstraint(
            "provider", "idempotency_key", name="uq_tool_effects_provider_idempotency"
        ),
        Index("ix_tool_effects_run_step", "run_id", "step_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_id: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(255), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    response_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    run: Mapped[WorkflowRun] = relationship("WorkflowRun")
