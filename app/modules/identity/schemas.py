"""Pydantic schemas for authentication and identity operations."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserSignupRequest(BaseModel):
    """Payload for registering a new user."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)


class UserLoginRequest(BaseModel):
    """Payload for user authentication."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    """Public representation of an authenticated user."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str
    created_at: datetime


class TokenResponse(BaseModel):
    """Standard token response format returned upon authentication."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = 900
    user: UserResponse


class OrgMembershipItem(BaseModel):
    """Organization membership summary for user profile."""

    model_config = ConfigDict(from_attributes=True)

    org_id: UUID
    org_name: str
    role: str


class MeResponse(BaseModel):
    """Full authenticated user profile with organization memberships."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str
    created_at: datetime
    memberships: list[OrgMembershipItem]
