"""HTTP endpoints for authentication, token rotation, and profile management."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_csrf_header
from app.core.config import Settings, get_settings
from app.infrastructure.db.session import get_session
from app.modules.identity.models import User
from app.modules.identity.schemas import (
    MeResponse,
    TokenResponse,
    UserLoginRequest,
    UserSignupRequest,
)
from app.modules.identity.service import IdentityService

router = APIRouter(tags=["Identity"])


def _set_refresh_cookie(
    response: Response,
    refresh_token: str,
    settings: Settings,
) -> None:
    """Set hardened HttpOnly refresh cookie."""
    is_secure = settings.app_env != "dev"
    response.set_cookie(
        key="ff_refresh",
        value=refresh_token,
        max_age=settings.refresh_token_ttl_seconds,
        httponly=True,
        samesite="strict",
        path="/v1/auth",
        secure=is_secure,
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    """Clear refresh cookie on logout."""
    is_secure = settings.app_env != "dev"
    response.delete_cookie(
        key="ff_refresh",
        path="/v1/auth",
        httponly=True,
        samesite="strict",
        secure=is_secure,
    )


@router.post(
    "/auth/signup",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
async def signup(
    payload: UserSignupRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    service = IdentityService(session, settings)
    token_resp, raw_refresh = await service.signup(payload)
    _set_refresh_cookie(response, raw_refresh, settings)
    return token_resp


@router.post(
    "/auth/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate user credentials",
)
async def login(
    payload: UserLoginRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    service = IdentityService(session, settings)
    token_resp, raw_refresh = await service.login(payload)
    _set_refresh_cookie(response, raw_refresh, settings)
    return token_resp


@router.post(
    "/auth/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_csrf_header)],
    summary="Rotate refresh token and mint a new access token",
)
async def refresh_token(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    ff_refresh: Annotated[str | None, Cookie()] = None,
) -> TokenResponse:
    service = IdentityService(session, settings)
    token_resp, new_raw_refresh = await service.refresh(ff_refresh)
    _set_refresh_cookie(response, new_raw_refresh, settings)
    return token_resp


@router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf_header)],
    summary="Revoke session and clear refresh cookie",
)
async def logout(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    ff_refresh: Annotated[str | None, Cookie()] = None,
) -> None:
    service = IdentityService(session, settings)
    await service.logout(ff_refresh)
    _clear_refresh_cookie(response, settings)


@router.get(
    "/me",
    response_model=MeResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve current authenticated user profile and memberships",
)
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MeResponse:
    service = IdentityService(session, settings)
    return await service.get_me(current_user)
