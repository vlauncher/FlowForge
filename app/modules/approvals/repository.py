"""Repository for approval_requests data access."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import decode_cursor, encode_cursor
from app.modules.approvals.models import ApprovalRequest
from app.modules.organizations.models import Membership


class ApprovalRepository:
    """Data access repository for human approval requests."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_approval(
        self,
        *,
        org_id: UUID,
        run_id: UUID,
        step_id: str,
        version_id: UUID,
        assigned_role: str,
        summary: dict[str, Any],
        expires_at: datetime,
    ) -> ApprovalRequest:
        """Create a new pending approval request."""
        approval = ApprovalRequest(
            id=uuid.uuid4(),
            org_id=org_id,
            run_id=run_id,
            step_id=step_id,
            version_id=version_id,
            assigned_role=assigned_role,
            state="PENDING",
            summary=summary,
            expires_at=expires_at,
        )
        self.session.add(approval)
        await self.session.flush()
        return approval

    async def get_by_id(
        self,
        approval_id: UUID,
        *,
        org_id: UUID,
    ) -> ApprovalRequest | None:
        """Fetch an approval request scoped to an organization."""
        stmt = (
            select(ApprovalRequest)
            .where(ApprovalRequest.id == approval_id)
            .where(ApprovalRequest.org_id == org_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_with_membership(
        self,
        approval_id: UUID,
        *,
        user_id: UUID,
    ) -> tuple[ApprovalRequest, str] | None:
        """Fetch an approval request asserting caller is a member of its organization."""
        stmt = (
            select(ApprovalRequest, Membership.role)
            .join(Membership, Membership.org_id == ApprovalRequest.org_id)
            .where(ApprovalRequest.id == approval_id)
            .where(Membership.user_id == user_id)
        )
        result = await self.session.execute(stmt)
        row = result.first()
        if not row:
            return None
        return row[0], row[1]

    async def list_approvals(
        self,
        *,
        org_id: UUID,
        state: str | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> tuple[list[ApprovalRequest], str | None]:
        """List approval requests for an organization with keyset pagination."""
        stmt = select(ApprovalRequest).where(ApprovalRequest.org_id == org_id)

        if state:
            stmt = stmt.where(ApprovalRequest.state == state)

        if cursor:
            payload = decode_cursor(cursor)
            stmt = stmt.where(
                tuple_(ApprovalRequest.created_at, ApprovalRequest.id)
                < (payload.created_at, payload.id)
            )

        stmt = stmt.order_by(ApprovalRequest.created_at.desc(), ApprovalRequest.id.desc()).limit(
            limit + 1
        )

        result = await self.session.execute(stmt)
        rows: Sequence[ApprovalRequest] = result.scalars().all()

        has_next = len(rows) > limit
        selected = list(rows[:limit])

        next_cursor: str | None = None
        if has_next and selected:
            last = selected[-1]
            next_cursor = encode_cursor(last.created_at, last.id)

        return selected, next_cursor

    async def decide_approval_atomic(
        self,
        *,
        org_id: UUID,
        approval_id: UUID,
        new_state: str,
        decided_by: UUID,
        comment: str | None,
    ) -> tuple[UUID, str, UUID] | None:
        """Atomically transition a PENDING approval if unexpired.

        Returns (run_id, step_id, version_id) if successful, None if rowcount was 0.
        """
        stmt = text("""
            UPDATE approval_requests
            SET state = :new_state,
                decided_by = :decided_by,
                decided_at = now(),
                decision_comment = :comment
            WHERE id = :approval_id
              AND org_id = :org_id
              AND state = 'PENDING'
              AND expires_at > now()
            RETURNING run_id, step_id, version_id;
        """)
        result = await self.session.execute(
            stmt,
            {
                "new_state": new_state,
                "decided_by": decided_by,
                "comment": comment,
                "approval_id": approval_id,
                "org_id": org_id,
            },
        )
        row = result.mappings().first()
        if not row:
            return None
        return row["run_id"], row["step_id"], row["version_id"]
