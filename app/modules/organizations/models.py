"""Organizations and memberships database models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import new_id
from app.infrastructure.db.base import Base

if TYPE_CHECKING:
    from app.modules.identity.models import User
    from app.modules.workflows.models import Workflow


class Organization(Base):
    """Organization tenant model."""

    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint("budget_limit_micro_usd >= 0", name="budget_non_negative"),
        CheckConstraint(
            "max_concurrent_runs >= 1 AND max_concurrent_runs <= 100",
            name="concurrent_runs_range",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    slug: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    plan: Mapped[str] = mapped_column(String(20), nullable=False, default="free")
    budget_limit_micro_usd: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=5_000_000,
    )
    max_concurrent_runs: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=5,
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

    memberships: Mapped[list[Membership]] = relationship(
        "Membership",
        back_populates="organization",
        lazy="raise",
        cascade="all, delete-orphan",
    )
    workflows: Mapped[list[Workflow]] = relationship(
        "Workflow",
        back_populates="organization",
        lazy="raise",
        cascade="all, delete-orphan",
    )


class Membership(Base):
    """User membership and role within an organization."""

    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_memberships_org_user"),
        CheckConstraint(
            "role IN ('owner', 'admin', 'operator', 'reviewer', 'viewer')",
            name="valid_role",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
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
        back_populates="memberships",
        lazy="raise",
    )
    user: Mapped[User] = relationship(
        "User",
        back_populates="memberships",
        lazy="raise",
    )
