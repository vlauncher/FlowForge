"""Execution database models for workflow_runs, step_attempts, and outbox_events."""

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
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import new_id
from app.infrastructure.db.base import Base

if TYPE_CHECKING:
    from app.modules.workflows.models import Workflow, WorkflowVersion


class WorkflowRun(Base):
    """Represents a single execution of a workflow."""

    __tablename__ = "workflow_runs"
    __table_args__ = (
        CheckConstraint(
            "state IN ('QUEUED', 'RUNNING', 'WAITING_APPROVAL', "
            "'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="ck_workflow_runs_state",
        ),
        CheckConstraint(
            "trigger_kind IN ('manual', 'webhook')",
            name="ck_workflow_runs_trigger_kind",
        ),
        UniqueConstraint("org_id", "idempotency_key", name="ix_workflow_runs_org_idempotency"),
        Index("ix_workflow_runs_org_created_id", "org_id", "created_at", "id"),
        Index("ix_workflow_runs_state_next_attempt", "state", "next_attempt_at"),
        Index("ix_workflow_runs_org_state", "org_id", "state"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflow_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    trigger_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    trigger_id: Mapped[UUID | None] = mapped_column(nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    outputs: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    current_step_id: Mapped[str | None] = mapped_column(String(120), nullable=True)

    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(default=False, nullable=False)

    lease_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_epoch: Mapped[int] = mapped_column(default=0, nullable=False)

    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    workflow: Mapped[Workflow] = relationship("Workflow")
    version: Mapped[WorkflowVersion] = relationship("WorkflowVersion")
    step_attempts: Mapped[list[StepAttempt]] = relationship(
        "StepAttempt",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="StepAttempt.started_at, StepAttempt.attempt_no",
    )


class StepAttempt(Base):
    """Execution attempt of an individual step in a workflow run."""

    __tablename__ = "step_attempts"
    __table_args__ = (
        CheckConstraint("attempt_no >= 1", name="ck_step_attempts_attempt_no"),
        CheckConstraint(
            "status IN ('RUNNING', 'SUCCEEDED', 'FAILED')",
            name="ck_step_attempts_status",
        ),
        UniqueConstraint(
            "run_id", "step_id", "attempt_no", name="uq_step_attempts_run_step_attempt"
        ),
        Index("ix_step_attempts_run_started", "run_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_id: Mapped[str] = mapped_column(String(120), nullable=False)
    step_type: Mapped[str] = mapped_column(String(50), nullable=False)
    attempt_no: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    input: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    retryable: Mapped[bool | None] = mapped_column(nullable=True)
    epoch: Mapped[int] = mapped_column(nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)

    run: Mapped[WorkflowRun] = relationship("WorkflowRun", back_populates="step_attempts")


class OutboxEvent(Base):
    """Transactional outbox event to be dispatched to RabbitMQ."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('RunRequested', 'RunResumeRequested', 'RunCancelRequested')",
            name="ck_outbox_events_event_type",
        ),
        Index("ix_outbox_events_next_publish", "next_publish_at"),
        Index("ix_outbox_events_unpublished_ordering", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    aggregate_type: Mapped[str] = mapped_column(String(50), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    schema_version: Mapped[int] = mapped_column(default=1, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    publish_attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    next_publish_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
