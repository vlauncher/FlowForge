"""Pydantic schemas for human approval gates."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApprovalDecisionRequest(BaseModel):
    """Payload to decide a pending approval request."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    comment: str | None = Field(default=None, max_length=1000)


class ApprovalOut(BaseModel):
    """Public representation of an approval request."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    run_id: UUID
    step_id: str
    version_id: UUID
    assigned_role: str
    state: str
    summary: dict[str, Any]
    expires_at: datetime
    decided_by: UUID | None = None
    decided_at: datetime | None = None
    decision_comment: str | None = None
    created_at: datetime


class ApprovalsPageResponse(BaseModel):
    """Paginated collection of approval requests."""

    items: list[ApprovalOut]
    next_cursor: str | None = None
