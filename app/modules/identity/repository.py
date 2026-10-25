"""Database repository for users and refresh token persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import RefreshToken, User


class IdentityRepository:
    """Encapsulates database operations on users and refresh tokens."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_email(self, email: str) -> User | None:
        """Find user by lowercase email address."""
        stmt = select(User).where(User.email == email.lower().strip())
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: UUID) -> User | None:
        """Find user by UUID."""
        stmt = select(User).where(User.id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_user(
        self,
        *,
        email: str,
        password_hash: str,
        display_name: str,
    ) -> User:
        """Persist a new user entity."""
        user = User(
            email=email.lower().strip(),
            password_hash=password_hash,
            display_name=display_name.strip(),
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def create_refresh_token(
        self,
        *,
        user_id: UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> RefreshToken:
        """Persist a new cryptographic refresh token row."""
        token = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.session.add(token)
        await self.session.flush()
        return token

    async def get_refresh_token_by_hash(self, token_hash: str) -> RefreshToken | None:
        """Find refresh token by its SHA-256 hash."""
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def revoke_token(self, token: RefreshToken, *, replaced_by: UUID | None = None) -> None:
        """Mark a single refresh token as revoked."""
        token.revoked_at = datetime.now(UTC)
        if replaced_by:
            token.replaced_by = replaced_by
        await self.session.flush()

    async def revoke_token_chain(self, start_token: RefreshToken) -> None:
        """Revoke a compromised token and all descendants in its rotation chain."""
        now = datetime.now(UTC)
        current_id: UUID | None = start_token.id

        # Track visited IDs to avoid potential infinite loops
        visited: set[UUID] = set()

        while current_id and current_id not in visited:
            visited.add(current_id)
            stmt = (
                update(RefreshToken)
                .where(RefreshToken.id == current_id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            await self.session.execute(stmt)

            # Find next token replaced by this one
            next_stmt = select(RefreshToken.replaced_by).where(RefreshToken.id == current_id)
            res = await self.session.execute(next_stmt)
            current_id = res.scalar_one_or_none()
        await self.session.flush()

    async def get_user_memberships(self, user_id: UUID) -> list[tuple[UUID, str, str]]:
        """Retrieve user's organization memberships (org_id, org_name, role)."""
        from app.modules.organizations.models import Membership, Organization

        stmt = (
            select(Membership.org_id, Organization.name, Membership.role)
            .join(Organization, Organization.id == Membership.org_id)
            .where(Membership.user_id == user_id)
            .order_by(Organization.name.asc())
        )
        result = await self.session.execute(stmt)
        return [(row[0], row[1], row[2]) for row in result.all()]
