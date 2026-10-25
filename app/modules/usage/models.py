"""Usage record database model for AI step token and cost tracking."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class UsageRecord(Base):
    """Immutable ledger of LLM generation calls and token usage."""

    __tablename__ = "usage_records"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(),
        primary_key=True,
        default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_id: Mapped[str] = mapped_column(
        sa.Text(),
        nullable=False,
    )
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("step_attempts.id", ondelete="SET NULL"),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(
        sa.Text(),
        nullable=False,
    )
    model_name: Mapped[str] = mapped_column(
        sa.Text(),
        nullable=False,
    )
    prompt_tokens: Mapped[int] = mapped_column(
        sa.Integer(),
        nullable=False,
    )
    completion_tokens: Mapped[int] = mapped_column(
        sa.Integer(),
        nullable=False,
    )
    total_tokens: Mapped[int] = mapped_column(
        sa.Integer(),
        nullable=False,
    )
    estimated_cost_micro_usd: Mapped[int] = mapped_column(
        sa.BigInteger(),
        nullable=False,
    )
    billed_cost_micro_usd: Mapped[int] = mapped_column(
        sa.BigInteger(),
        nullable=False,
        server_default=sa.text("0"),
    )
    latency_ms: Mapped[int] = mapped_column(
        sa.Integer(),
        nullable=False,
    )
    prompt_template_id: Mapped[str] = mapped_column(
        sa.Text(),
        nullable=False,
    )
    prompt_template_version: Mapped[int] = mapped_column(
        sa.Integer(),
        nullable=False,
    )
    outcome: Mapped[str] = mapped_column(
        sa.Text(),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


class BudgetReservation(Base):
    """Two-phase budget reservation for AI step execution."""

    __tablename__ = "budget_reservations"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(),
        primary_key=True,
        default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_id: Mapped[str] = mapped_column(
        sa.Text(),
        nullable=False,
    )
    reserved_micro_usd: Mapped[int] = mapped_column(
        sa.BigInteger(),
        nullable=False,
    )
    settled_micro_usd: Mapped[int | None] = mapped_column(
        sa.BigInteger(),
        nullable=True,
    )
    state: Mapped[str] = mapped_column(
        sa.String(30),
        nullable=False,
        default="RESERVED",
    )
    settled_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        onupdate=sa.text("now()"),
        nullable=False,
    )
