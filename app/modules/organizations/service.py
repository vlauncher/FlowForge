"""Business logic for organization management and membership administration."""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ForbiddenError, LastOwnerError, NotFoundError
from app.core.pagination import Page, decode_cursor, encode_cursor
from app.domain.permissions import can_manage_member_role
from app.modules.audit.repository import AuditRepository
from app.modules.identity.models import User
from app.modules.identity.repository import IdentityRepository
from app.modules.organizations.repository import OrganizationRepository
from app.modules.organizations.schemas import (
    AddMemberRequest,
    MemberResponse,
    OrganizationCreateRequest,
    OrganizationResponse,
    UpdateMemberRoleRequest,
)

NON_ALPHANUM_RE = re.compile(r"[^a-z0-9]+")


def generate_slug(name: str) -> str:
    """Generate a clean URL slug from an organization name."""
    cleaned = NON_ALPHANUM_RE.sub("-", name.lower()).strip("-")
    if len(cleaned) < 3:
        cleaned = f"org-{cleaned}".strip("-")
    return cleaned[:40]


class OrganizationService:
    """Orchestrates organization provisioning and RBAC team management."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = OrganizationRepository(session)
        self.identity_repo = IdentityRepository(session)

    async def create_organization(
        self,
        req: OrganizationCreateRequest,
        user: User,
    ) -> OrganizationResponse:
        """Create a new organization and assign the creator as the founding owner."""
        slug_candidate = req.slug
        if slug_candidate:
            existing = await self.repo.get_by_slug(slug_candidate)
            if existing:
                raise ConflictError(f"Organization slug '{slug_candidate}' is already taken")
        else:
            base_slug = generate_slug(req.name)
            slug_candidate = base_slug
            attempt = 1
            while attempt <= 5:
                existing = await self.repo.get_by_slug(slug_candidate)
                if not existing:
                    break
                attempt += 1
                suffix = f"-{attempt}"
                slug_candidate = f"{base_slug[: 40 - len(suffix)]}{suffix}"
            else:
                raise ConflictError(
                    "Unable to derive unique organization slug; please provide one explicitly"
                )

        org = await self.repo.create_organization(
            name=req.name.strip(),
            slug=slug_candidate,
        )

        await self.repo.add_membership(
            org_id=org.id,
            user_id=user.id,
            role="owner",
        )

        audit_repo = AuditRepository(self.session)
        await audit_repo.record_audit_event(
            org_id=org.id,
            actor_user_id=user.id,
            actor_type="user",
            action="org.created",
            target_type="organization",
            target_id=org.id,
            metadata={"name": org.name, "slug": org.slug},
        )

        await self.session.commit()

        return OrganizationResponse(
            id=org.id,
            name=org.name,
            slug=org.slug,
            plan=org.plan,
            budget_limit_micro_usd=org.budget_limit_micro_usd,
            max_concurrent_runs=org.max_concurrent_runs,
            created_at=org.created_at,
            my_role="owner",
        )

    async def list_user_organizations(
        self,
        user: User,
        *,
        limit: int = 20,
        cursor: str | None = None,
    ) -> Page[OrganizationResponse]:
        """List all organizations the user is a member of with keyset pagination."""
        parsed_cursor = decode_cursor(cursor) if cursor else None
        items, has_more = await self.repo.list_user_organizations(
            user.id,
            cursor=parsed_cursor,
            limit=limit,
        )

        responses = [
            OrganizationResponse(
                id=org.id,
                name=org.name,
                slug=org.slug,
                plan=org.plan,
                budget_limit_micro_usd=org.budget_limit_micro_usd,
                max_concurrent_runs=org.max_concurrent_runs,
                created_at=org.created_at,
                my_role=role,
            )
            for org, role in items
        ]

        next_cursor = None
        if has_more and items:
            last_org, _ = items[-1]
            next_cursor = encode_cursor(last_org.created_at, last_org.id)

        return Page(items=responses, next_cursor=next_cursor, has_more=has_more)

    async def get_organization(
        self,
        org_id: UUID,
        user: User,
    ) -> OrganizationResponse:
        """Fetch organization details, asserting caller membership to prevent existence leakage."""
        membership = await self.repo.get_membership(org_id=org_id, user_id=user.id)
        if not membership:
            raise NotFoundError("Organization not found")

        org = await self.repo.get_by_id(org_id)
        if not org:
            raise NotFoundError("Organization not found")

        return OrganizationResponse(
            id=org.id,
            name=org.name,
            slug=org.slug,
            plan=org.plan,
            budget_limit_micro_usd=org.budget_limit_micro_usd,
            max_concurrent_runs=org.max_concurrent_runs,
            created_at=org.created_at,
            my_role=membership.role,
        )

    async def list_members(
        self,
        *,
        org_id: UUID,
        limit: int = 20,
        cursor: str | None = None,
    ) -> Page[MemberResponse]:
        """List organization members with keyset pagination."""
        parsed_cursor = decode_cursor(cursor) if cursor else None
        items, has_more = await self.repo.list_members(
            org_id=org_id,
            cursor=parsed_cursor,
            limit=limit,
        )

        responses = [
            MemberResponse(
                user_id=usr.id,
                email=usr.email,
                display_name=usr.display_name,
                role=mem.role,
                created_at=mem.created_at,
            )
            for mem, usr in items
        ]

        next_cursor = None
        if has_more and items:
            last_mem, _ = items[-1]
            next_cursor = encode_cursor(last_mem.created_at, last_mem.id)

        return Page(items=responses, next_cursor=next_cursor, has_more=has_more)

    async def add_member(
        self,
        *,
        org_id: UUID,
        req: AddMemberRequest,
        actor_role: str,
    ) -> MemberResponse:
        """Add an existing user to an organization."""
        if not can_manage_member_role(actor_role, None, req.role):
            raise ForbiddenError("You lack permission to assign this role")

        target_user = await self.identity_repo.get_by_email(req.email)
        if not target_user:
            raise NotFoundError(f"No user found with email '{req.email}'")

        existing_membership = await self.repo.get_membership(
            org_id=org_id,
            user_id=target_user.id,
        )
        if existing_membership:
            raise ConflictError("User is already a member of this organization")

        membership = await self.repo.add_membership(
            org_id=org_id,
            user_id=target_user.id,
            role=req.role,
        )

        audit_repo = AuditRepository(self.session)
        await audit_repo.record_audit_event(
            org_id=org_id,
            actor_user_id=None,
            actor_type="user",
            action="member.added",
            target_type="membership",
            target_id=membership.id,
            metadata={"user_id": str(target_user.id), "email": target_user.email, "role": req.role},
        )

        await self.session.commit()

        return MemberResponse(
            user_id=target_user.id,
            email=target_user.email,
            display_name=target_user.display_name,
            role=membership.role,
            created_at=membership.created_at,
        )

    async def update_member_role(
        self,
        *,
        org_id: UUID,
        target_user_id: UUID,
        req: UpdateMemberRoleRequest,
        actor_role: str,
    ) -> MemberResponse:
        """Modify an existing member's role while enforcing last-owner safety invariants."""
        target_membership = await self.repo.get_membership(
            org_id=org_id,
            user_id=target_user_id,
        )
        if not target_membership:
            raise NotFoundError("Member not found in organization")

        if not can_manage_member_role(actor_role, target_membership.role, req.role):
            raise ForbiddenError("You lack permission to modify this member's role")

        # Invariant: organization must retain at least one owner
        if target_membership.role == "owner" and req.role != "owner":
            # Pessimistic locking: lock all owners in this org
            owners = await self.repo.get_owner_memberships_for_update(org_id=org_id)
            if len(owners) <= 1:
                raise LastOwnerError("Cannot demote the last owner of an organization")

        old_role = target_membership.role
        target_membership.role = req.role

        audit_repo = AuditRepository(self.session)
        await audit_repo.record_audit_event(
            org_id=org_id,
            actor_user_id=None,
            actor_type="user",
            action="member.role_changed",
            target_type="membership",
            target_id=target_membership.id,
            metadata={"user_id": str(target_user_id), "old_role": old_role, "new_role": req.role},
        )

        await self.session.commit()

        target_user = await self.identity_repo.get_by_id(target_user_id)
        assert target_user is not None

        return MemberResponse(
            user_id=target_user.id,
            email=target_user.email,
            display_name=target_user.display_name,
            role=target_membership.role,
            created_at=target_membership.created_at,
        )
