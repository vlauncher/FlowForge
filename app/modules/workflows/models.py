"""Workflows and workflow versions database models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import new_id
from app.infrastructure.db.base import Base

if TYPE_CHECKING:
    from app.modules.identity.models import User
    from app.modules.organizations.models import Organization


class Workflow(Base):
    """Workflow entity containing metadata and referencing published versions."""

    __tablename__ = "workflows"
    __table_args__ = (
        Index(
            "ix_workflows_org_created_id",
            "org_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    current_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "workflow_versions.id",
            ondelete="SET NULL",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
            name="fk_workflows_current_version_id",
        ),
        nullable=True,
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    organization: Mapped[Organization] = relationship(
        "Organization",
        back_populates="workflows",
        lazy="raise",
    )
    creator: Mapped[User | None] = relationship("User", lazy="raise")
    versions: Mapped[list[WorkflowVersion]] = relationship(
        "WorkflowVersion",
        back_populates="workflow",
        lazy="raise",
        cascade="all, delete-orphan",
        foreign_keys="[WorkflowVersion.workflow_id]",
    )


class WorkflowVersion(Base):
    """Immutable versioned definition of a directed workflow DAG."""

    __tablename__ = "workflow_versions"
    __table_args__ = (
        UniqueConstraint("workflow_id", "version", name="uq_workflow_versions_workflow_version"),
        CheckConstraint("status IN ('draft', 'published')", name="valid_status"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "(status != 'published') OR (checksum IS NOT NULL AND published_at IS NOT NULL)",
            name="published_version_requires_checksum",
        ),
        Index(
            "ix_workflow_versions_single_draft",
            "workflow_id",
            unique=True,
            postgresql_where="status = 'draft'",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    workflow_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    definition_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    workflow: Mapped[Workflow] = relationship(
        "Workflow",
        back_populates="versions",
        foreign_keys=[workflow_id],
        lazy="raise",
    )
