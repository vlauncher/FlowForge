"""Business logic for user onboarding, authentication, and session rotation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import EmailTakenError, InvalidCredentialsError, UnauthenticatedError
from app.core.security import (
    check_needs_rehash,
    create_access_token,
    hash_password,
    hash_token,
    new_refresh_token,
    verify_dummy_password,
    verify_password,
)
from app.modules.audit.repository import AuditRepository
from app.modules.identity.models import User
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.schemas import (
    MeResponse,
    OrgMembershipItem,
    TokenResponse,
    UserLoginRequest,
    UserResponse,
    UserSignupRequest,
)


class IdentityService:
    """Orchestrates identity and authentication workflows."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.repo = IdentityRepository(session)
        self.settings = settings or get_settings()

    async def signup(self, req: UserSignupRequest) -> tuple[TokenResponse, str]:
        """Register a new user account and mint initial credentials."""
        existing = await self.repo.get_by_email(req.email)
        if existing:
            raise EmailTakenError("An account with this email address already exists")

        pw_hash = hash_password(req.password)
        user = await self.repo.create_user(
            email=req.email,
            password_hash=pw_hash,
            display_name=req.display_name,
        )

        access_token = create_access_token(user.id, settings=self.settings)
        raw_refresh = new_refresh_token()
        refresh_hash = hash_token(raw_refresh)
        expires_at = datetime.now(UTC) + timedelta(seconds=self.settings.refresh_token_ttl_seconds)

        await self.repo.create_refresh_token(
            user_id=user.id,
            token_hash=refresh_hash,
            expires_at=expires_at,
        )

        audit_repo = AuditRepository(self.session)
        await audit_repo.record_audit_event(
            org_id=None,
            actor_user_id=user.id,
            actor_type="user",
            action="user.signup",
            target_type="user",
            target_id=user.id,
            metadata={"email": user.email},
        )

        await self.session.commit()

        token_resp = TokenResponse(
            access_token=access_token,
            expires_in=self.settings.access_token_ttl_seconds,
            user=UserResponse.model_validate(user),
        )
        return token_resp, raw_refresh

    async def login(self, req: UserLoginRequest) -> tuple[TokenResponse, str]:
        """Authenticate user credentials using constant-time timing defenses."""
        user = await self.repo.get_by_email(req.email)
        if not user or not user.is_active:
            # Constant-time timing defense against account enumeration
            verify_dummy_password(req.password)
            raise InvalidCredentialsError("Invalid email or password")

        if not verify_password(req.password, user.password_hash):
            raise InvalidCredentialsError("Invalid email or password")

        if check_needs_rehash(user.password_hash):
            user.password_hash = hash_password(req.password)

        access_token = create_access_token(user.id, settings=self.settings)
        raw_refresh = new_refresh_token()
        refresh_hash = hash_token(raw_refresh)
        expires_at = datetime.now(UTC) + timedelta(seconds=self.settings.refresh_token_ttl_seconds)

        await self.repo.create_refresh_token(
            user_id=user.id,
            token_hash=refresh_hash,
            expires_at=expires_at,
        )

        audit_repo = AuditRepository(self.session)
        await audit_repo.record_audit_event(
            org_id=None,
            actor_user_id=user.id,
            actor_type="user",
            action="user.login",
            target_type="user",
            target_id=user.id,
            metadata={"email": user.email},
        )

        await self.session.commit()

        token_resp = TokenResponse(
            access_token=access_token,
            expires_in=self.settings.access_token_ttl_seconds,
            user=UserResponse.model_validate(user),
        )
        return token_resp, raw_refresh

    async def refresh(self, raw_refresh_token: str | None) -> tuple[TokenResponse, str]:
        """Rotate a refresh token, revoking the chain if a used token is presented."""
        if not raw_refresh_token:
            raise UnauthenticatedError("Refresh token cookie missing")

        token_hash = hash_token(raw_refresh_token)
        stored_token = await self.repo.get_refresh_token_by_hash(token_hash)
        if not stored_token:
            raise UnauthenticatedError("Invalid refresh token")

        # Reuse of revoked token triggers full chain revocation (theft mitigation)
        if stored_token.revoked_at is not None:
            await self.repo.revoke_token_chain(stored_token)
            await self.session.commit()
            raise UnauthenticatedError("Refresh token has been revoked")

        if stored_token.expires_at <= datetime.now(UTC):
            raise UnauthenticatedError("Refresh token has expired")

        user = await self.repo.get_by_id(stored_token.user_id)
        if not user or not user.is_active:
            raise UnauthenticatedError("User account inactive or not found")

        # Mint new tokens
        access_token = create_access_token(user.id, settings=self.settings)
        new_raw_refresh = new_refresh_token()
        new_hash = hash_token(new_raw_refresh)
        expires_at = datetime.now(UTC) + timedelta(seconds=self.settings.refresh_token_ttl_seconds)

        new_stored = await self.repo.create_refresh_token(
            user_id=user.id,
            token_hash=new_hash,
            expires_at=expires_at,
        )

        # Invalidate old token and link forward
        await self.repo.revoke_token(stored_token, replaced_by=new_stored.id)

        await self.session.commit()

        token_resp = TokenResponse(
            access_token=access_token,
            expires_in=self.settings.access_token_ttl_seconds,
            user=UserResponse.model_validate(user),
        )
        return token_resp, new_raw_refresh

    async def logout(self, raw_refresh_token: str | None) -> None:
        """Revoke the active refresh token session."""
        if raw_refresh_token:
            token_hash = hash_token(raw_refresh_token)
            stored_token = await self.repo.get_refresh_token_by_hash(token_hash)
            if stored_token and stored_token.revoked_at is None:
                await self.repo.revoke_token(stored_token)
                await self.session.commit()

    async def get_me(self, user: User) -> MeResponse:
        """Build authenticated user profile with organization membership roles."""
        memberships = await self.repo.get_user_memberships(user.id)
        items = [OrgMembershipItem(org_id=m[0], org_name=m[1], role=m[2]) for m in memberships]
        return MeResponse(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            created_at=user.created_at,
            memberships=items,
        )
