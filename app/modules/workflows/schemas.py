"""Pydantic schemas for workflow and version entities."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WorkflowCreateRequest(BaseModel):
    """Payload to create a new workflow."""

    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)


class WorkflowResponse(BaseModel):
    """Public representation of a workflow entity."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    display_name: str
    description: str | None = None
    current_version_id: UUID | None = None
    archived_at: datetime | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


class ValidationIssueSchema(BaseModel):
    """Individual graph validation issue details."""

    code: str
    field: str
    message: str
    step_ids: list[str] = Field(default_factory=list)


class WorkflowVersionCreateRequest(BaseModel):
    """Payload to create a new workflow version draft."""

    model_config = ConfigDict(extra="forbid")
    definition: dict[str, Any]
    from_version: int | None = None


class WorkflowVersionUpdateRequest(BaseModel):
    """Payload to update an existing workflow version draft."""

    model_config = ConfigDict(extra="forbid")
    definition: dict[str, Any]


class WorkflowValidateRequest(BaseModel):
    """Payload to validate a workflow definition."""

    model_config = ConfigDict(extra="forbid")
    definition: dict[str, Any]


class WorkflowValidateResponse(BaseModel):
    """Response returned by definition validation endpoint."""

    valid: bool
    checksum: str | None = None
    errors: list[ValidationIssueSchema] = Field(default_factory=list)


class WorkflowPublishRequest(BaseModel):
    """Payload to publish a workflow version."""

    model_config = ConfigDict(extra="forbid")
    version: int | None = None


class WorkflowVersionSummaryResponse(BaseModel):
    """Summary of a workflow version (excluding definition JSON)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workflow_id: UUID
    org_id: UUID
    version: int
    status: str
    schema_version: int
    checksum: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    published_at: datetime | None = None


class WorkflowVersionResponse(WorkflowVersionSummaryResponse):
    """Full workflow version details including definition JSON."""

    definition_json: dict[str, Any]
