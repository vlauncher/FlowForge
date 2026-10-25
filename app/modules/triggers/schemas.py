"""Pydantic schemas for triggers."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CreateTriggerRequest(BaseModel):
    """Payload to create a webhook trigger for a workflow."""

    model_config = ConfigDict(extra="forbid")

    credential_id: UUID


class TriggerOut(BaseModel):
    """Public representation of a workflow trigger."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workflow_id: UUID
    credential_id: UUID
    enabled: bool
    webhook_url: str
    created_at: datetime
