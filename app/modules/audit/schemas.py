"""Pydantic schemas for audit events."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AuditEventOut(BaseModel):
    """Public representation of an immutable audit event."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID | None = None
    actor_user_id: UUID | None = None
    actor_type: str
    action: str
    target_type: str
    target_id: UUID | None = None
    request_id: str | None = None
    redacted_metadata: dict[str, Any]
    created_at: datetime


class AuditEventsPageResponse(BaseModel):
    """Paginated collection of audit events."""

    items: list[AuditEventOut]
    next_cursor: str | None = None
