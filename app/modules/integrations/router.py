"""HTTP endpoints for organization integration credentials."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.infrastructure.db.session import get_session
from app.modules.identity.models import User
from app.modules.integrations.schemas import (
    CredentialCreateRequest,
    CredentialResponse,
    CredentialsPageResponse,
    RotateCredentialRequest,
)
from app.modules.integrations.service import IntegrationService

router = APIRouter(tags=["Integrations"])


@router.post(
    "/organizations/{org_id}/credentials",
    response_model=CredentialResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create integration credential",
)
async def create_credential(
    org_id: UUID,
    req: CredentialCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CredentialResponse:
    """Store write-only integration credentials encrypted with AES-256-GCM."""
    service = IntegrationService(session)
    return await service.create_credential(
        org_id=org_id,
        req=req,
        user_id=current_user.id,
    )


@router.get(
    "/organizations/{org_id}/credentials",
    response_model=CredentialsPageResponse,
    summary="List integration credentials",
)
async def list_credentials(
    org_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> CredentialsPageResponse:
    """List metadata for registered organization credentials (secrets are never returned)."""
    service = IntegrationService(session)
    return await service.list_credentials(
        org_id=org_id,
        user_id=current_user.id,
        limit=limit,
        cursor=cursor,
    )


@router.post(
    "/organizations/{org_id}/credentials/{credential_id}/rotate",
    response_model=CredentialResponse,
    status_code=status.HTTP_200_OK,
    summary="Rotate integration credential secret",
)
async def rotate_credential(
    org_id: UUID,
    credential_id: UUID,
    req: RotateCredentialRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CredentialResponse:
    """Update secret payload for an existing credential and re-encrypt under active key."""
    service = IntegrationService(session)
    return await service.rotate_credential(
        org_id=org_id,
        credential_id=credential_id,
        req=req,
        user_id=current_user.id,
    )
