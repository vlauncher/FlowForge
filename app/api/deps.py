"""FastAPI dependencies for authentication, tenancy, and permissions."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Header, Path
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, NotFoundError, UnauthenticatedError
from app.core.security import decode_access_token
from app.domain.permissions import Action, has_permission
from app.infrastructure.db.session import get_session
from app.modules.identity.models import User
from app.modules.organizations.models import Membership

http_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(http_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """Extract, decode, and validate access token, returning the authenticated User."""
    if not credentials or not credentials.credentials:
        raise UnauthenticatedError("Missing bearer authentication token")

    payload = decode_access_token(credentials.credentials)
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise UnauthenticatedError("Invalid token subject")

    try:
        user_id = UUID(user_id_str)
    except ValueError as err:
        raise UnauthenticatedError("Malformed user identifier in token") from err

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise UnauthenticatedError("User not found or deactivated")

    return user


async def get_membership(
    org_id: Annotated[UUID, Path(..., description="Organization UUID")],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Membership:
    """Load and verify user membership in the specified organization.

    Raises NotFoundError (404) if user is not a member, preventing
    existence leakage to unauthorized callers.
    """
    stmt = select(Membership).where(
        Membership.org_id == org_id,
        Membership.user_id == current_user.id,
    )
    result = await session.execute(stmt)
    membership = result.scalar_one_or_none()
    if not membership:
        raise NotFoundError("Organization not found")

    return membership


def require_permission(
    action: Action | str,
) -> Callable[..., Coroutine[Any, Any, Membership]]:
    """Dependency factory checking that caller's role in the organization grants action."""

    async def _dependency(
        membership: Annotated[Membership, Depends(get_membership)],
    ) -> Membership:
        if not has_permission(membership.role, action):
            raise ForbiddenError(f"Role '{membership.role}' lacks permission '{action}'")
        return membership

    return _dependency


def require_csrf_header(
    x_flowforge_csrf: Annotated[str | None, Header(alias="X-FlowForge-CSRF")] = None,
) -> None:
    """Enforce CSRF protection header on cookie-authenticated requests."""
    if x_flowforge_csrf != "1":
        raise ForbiddenError("Missing or invalid X-FlowForge-CSRF header")
