"""Pydantic schemas for integration credentials."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CredentialCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    provider: str = Field(min_length=1, max_length=100)
    secret: str = Field(min_length=1, max_length=4096)
    allowed_hosts: list[str] = Field(default_factory=list)
    permission_scopes: list[str] = Field(default_factory=list)


class RotateCredentialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    secret: str = Field(min_length=1, max_length=4096)


class CredentialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    org_id: UUID
    name: str
    provider: str
    allowed_hosts: list[str]
    permission_scopes: list[str]
    key_id: str
    created_at: datetime
    rotated_at: datetime | None = None


class CredentialsPageResponse(BaseModel):
    items: list[CredentialResponse]
    next_cursor: str | None = None
