"""HTTP endpoints for organization provisioning and member RBAC operations."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_membership, require_permission
from app.core.pagination import Page
from app.domain.permissions import Action
from app.infrastructure.db.session import get_session
from app.modules.identity.models import User
from app.modules.organizations.models import Membership
from app.modules.organizations.schemas import (
    AddMemberRequest,
    MemberResponse,
    OrganizationCreateRequest,
    OrganizationResponse,
    UpdateMemberRoleRequest,
)
from app.modules.organizations.service import OrganizationService

router = APIRouter(prefix="/organizations", tags=["Organizations"])


@router.post(
    "",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new organization",
)
async def create_organization(
    payload: OrganizationCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OrganizationResponse:
    service = OrganizationService(session)
    return await service.create_organization(payload, current_user)


@router.get(
    "",
    response_model=Page[OrganizationResponse],
    status_code=status.HTTP_200_OK,
    summary="List organizations caller belongs to",
)
async def list_organizations(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[OrganizationResponse]:
    service = OrganizationService(session)
    return await service.list_user_organizations(current_user, limit=limit, cursor=cursor)


@router.get(
    "/{org_id}",
    response_model=OrganizationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get organization details",
)
async def get_organization(
    org_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OrganizationResponse:
    service = OrganizationService(session)
    return await service.get_organization(org_id, current_user)


@router.get(
    "/{org_id}/members",
    response_model=Page[MemberResponse],
    status_code=status.HTTP_200_OK,
    summary="List organization members",
)
async def list_members(
    org_id: UUID,
    membership: Annotated[Membership, Depends(get_membership)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[MemberResponse]:
    service = OrganizationService(session)
    return await service.list_members(org_id=org_id, limit=limit, cursor=cursor)


@router.post(
    "/{org_id}/members",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a user to an organization",
)
async def add_member(
    org_id: UUID,
    payload: AddMemberRequest,
    membership: Annotated[Membership, Depends(require_permission(Action.MEMBER_MANAGE))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MemberResponse:
    service = OrganizationService(session)
    return await service.add_member(
        org_id=org_id,
        req=payload,
        actor_role=membership.role,
    )


@router.patch(
    "/{org_id}/members/{user_id}",
    response_model=MemberResponse,
    status_code=status.HTTP_200_OK,
    summary="Update an organization member's role",
)
async def update_member_role(
    org_id: UUID,
    user_id: UUID,
    payload: UpdateMemberRoleRequest,
    membership: Annotated[Membership, Depends(require_permission(Action.MEMBER_MANAGE))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MemberResponse:
    service = OrganizationService(session)
    return await service.update_member_role(
        org_id=org_id,
        target_user_id=user_id,
        req=payload,
        actor_role=membership.role,
    )
