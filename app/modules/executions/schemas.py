"""Pydantic schemas for workflow run triggering and execution tracking."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TriggerRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inputs: dict[str, Any] = Field(default_factory=dict)
    workflow_version: int | None = None


class RunActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    run_id: UUID
    state: str
    workflow_id: UUID
    workflow_version: int
    version_id: UUID
    status_url: str
    created_at: datetime


class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    org_id: UUID
    workflow_id: UUID
    workflow_version: int
    version_id: UUID
    state: str
    trigger_kind: str
    current_step_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class RunDetail(RunSummary):
    inputs: dict[str, Any]
    outputs: dict[str, Any] | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_detail: str | None = None
    cancel_requested: bool = False
    status_url: str


class StepAttemptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    run_id: UUID
    step_id: str
    step_type: str
    attempt_no: int
    status: str
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    error_code: str | None = None
    error_detail: str | None = None
    retryable: bool | None = None
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int | None = None


class StepAttemptsListResponse(BaseModel):
    items: list[StepAttemptResponse]


class RunsPageResponse(BaseModel):
    items: list[RunSummary]
    next_cursor: str | None = None
