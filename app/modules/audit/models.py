"""Database model for immutable audit events."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class AuditEvent(Base):
    """Immutable audit trail row tracking securable platform mutations."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(),
        primary_key=True,
        default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_type: Mapped[str] = mapped_column(
        sa.Text(),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(
        sa.Text(),
        nullable=False,
    )
    target_type: Mapped[str] = mapped_column(
        sa.Text(),
        nullable=False,
    )
    target_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(),
        nullable=True,
    )
    request_id: Mapped[str | None] = mapped_column(
        sa.Text(),
        nullable=True,
    )
    redacted_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB(),
        server_default=sa.text("'{}'::jsonb"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )
