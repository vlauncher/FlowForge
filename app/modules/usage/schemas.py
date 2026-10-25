"""Schemas for usage metrics and cost tracking (Phase 8)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UsageTotals(BaseModel):
    """Aggregate token and cost metrics."""

    model_config = ConfigDict(from_attributes=True)

    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_micro_usd: int = 0
    billed_cost_micro_usd: int = 0


class ModelUsageItem(BaseModel):
    """Per-model breakdown of tokens and cost."""

    model_config = ConfigDict(from_attributes=True)

    provider: str
    model_name: str
    calls: int
    total_tokens: int
    estimated_cost_micro_usd: int
    billed_cost_micro_usd: int


class OrgUsageResponse(BaseModel):
    """Organization usage and cost report within a time window."""

    model_config = ConfigDict(populate_by_name=True)

    org_id: UUID
    from_time: datetime = Field(..., serialization_alias="from")
    to_time: datetime = Field(..., serialization_alias="to")
    budget_limit_micro_usd: int
    totals: UsageTotals
    by_model: list[ModelUsageItem]
    runs_by_state: dict[str, int]
