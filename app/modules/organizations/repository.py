"""Database repository for organization and membership records."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import and_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import CursorPayload
from app.modules.identity.models import User
from app.modules.organizations.models import Membership, Organization


class OrganizationRepository:
    """Encapsulates database access for organizations and memberships."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, org_id: UUID) -> Organization | None:
        """Fetch organization by primary key."""
        stmt = select(Organization).where(Organization.id == org_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Organization | None:
        """Fetch organization by unique slug."""
        stmt = select(Organization).where(Organization.slug == slug)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_organization(
        self,
        *,
        name: str,
        slug: str,
    ) -> Organization:
        """Insert a new organization entity."""
        org = Organization(name=name, slug=slug)
        self.session.add(org)
        await self.session.flush()
        return org

    async def add_membership(
        self,
        *,
        org_id: UUID,
        user_id: UUID,
        role: str,
    ) -> Membership:
        """Insert a membership record associating user to organization."""
        membership = Membership(org_id=org_id, user_id=user_id, role=role)
        self.session.add(membership)
        await self.session.flush()
        return membership

    async def get_membership(
        self,
        *,
        org_id: UUID,
        user_id: UUID,
    ) -> Membership | None:
        """Retrieve user's membership in an organization."""
        stmt = select(Membership).where(
            and_(
                Membership.org_id == org_id,
                Membership.user_id == user_id,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_user_organizations(
        self,
        user_id: UUID,
        *,
        cursor: CursorPayload | None,
        limit: int,
    ) -> tuple[Sequence[tuple[Organization, str]], bool]:
        """List organizations the user belongs to, with keyset pagination."""
        stmt = (
            select(Organization, Membership.role)
            .join(Membership, Membership.org_id == Organization.id)
            .where(Membership.user_id == user_id)
        )

        if cursor:
            stmt = stmt.where(
                tuple_(Organization.created_at, Organization.id)
                < tuple_(cursor.created_at, cursor.id)
            )

        stmt = stmt.order_by(Organization.created_at.desc(), Organization.id.desc()).limit(
            limit + 1
        )
        result = await self.session.execute(stmt)
        rows = result.all()
        has_more = len(rows) > limit
        items = [(row[0], row[1]) for row in rows[:limit]]
        return items, has_more

    async def list_members(
        self,
        *,
        org_id: UUID,
        cursor: CursorPayload | None,
        limit: int,
    ) -> tuple[Sequence[tuple[Membership, User]], bool]:
        """List organization members with keyset pagination."""
        stmt = (
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.org_id == org_id)
        )

        if cursor:
            stmt = stmt.where(
                tuple_(Membership.created_at, Membership.id) < tuple_(cursor.created_at, cursor.id)
            )

        stmt = stmt.order_by(Membership.created_at.desc(), Membership.id.desc()).limit(limit + 1)
        result = await self.session.execute(stmt)
        rows = result.all()
        has_more = len(rows) > limit
        items = [(row[0], row[1]) for row in rows[:limit]]
        return items, has_more

    async def get_owner_memberships_for_update(
        self,
        *,
        org_id: UUID,
    ) -> Sequence[Membership]:
        """Lock and select all owner rows for the organization using SELECT FOR UPDATE."""
        stmt = (
            select(Membership)
            .where(
                and_(
                    Membership.org_id == org_id,
                    Membership.role == "owner",
                )
            )
            .with_for_update()
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
