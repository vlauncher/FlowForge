"""Schemas for organizations and membership management."""

from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

SLUG_REGEX = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")


class OrganizationCreateRequest(BaseModel):
    """Payload to create a new organization."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    slug: str | None = Field(default=None, min_length=3, max_length=40)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.lower().strip()
        if not SLUG_REGEX.match(cleaned):
            raise ValueError(
                "Slug must be 3-40 chars, lowercase alphanumeric and hyphens, "
                "not starting or ending with hyphen"
            )
        return cleaned


class OrganizationResponse(BaseModel):
    """Public representation of an organization including the caller's role."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    plan: str
    budget_limit_micro_usd: int
    max_concurrent_runs: int
    created_at: datetime
    my_role: str


class AddMemberRequest(BaseModel):
    """Payload to add a user to an organization."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    role: str = Field(pattern=r"^(owner|admin|operator|reviewer|viewer)$")


class UpdateMemberRoleRequest(BaseModel):
    """Payload to alter an existing member's role."""

    model_config = ConfigDict(extra="forbid")

    role: str = Field(pattern=r"^(owner|admin|operator|reviewer|viewer)$")


class MemberResponse(BaseModel):
    """Member profile within an organization."""

    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    email: str
    display_name: str
    role: str
    created_at: datetime
