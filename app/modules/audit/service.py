"""Business logic service for audit trail."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditEvent
from app.modules.audit.repository import AuditRepository
from app.modules.audit.schemas import AuditEventOut, AuditEventsPageResponse


class AuditService:
    """Service layer managing audit event capture and querying."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = AuditRepository(session)

    async def record_event(
        self,
        *,
        org_id: UUID | None,
        actor_user_id: UUID | None,
        actor_type: str,
        action: str,
        target_type: str,
        target_id: UUID | None = None,
        request_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent:
        """Record an immutable audit event."""
        return await self.repo.record_audit_event(
            org_id=org_id,
            actor_user_id=actor_user_id,
            actor_type=actor_type,
            action=action,
            target_type=target_type,
            target_id=target_id,
            request_id=request_id,
            metadata=metadata,
        )

    async def list_events(
        self,
        *,
        org_id: UUID,
        action: str | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> AuditEventsPageResponse:
        """List audit events for an organization."""
        items, next_cursor = await self.repo.list_audit_events(
            org_id=org_id,
            action=action,
            limit=limit,
            cursor=cursor,
        )
        return AuditEventsPageResponse(
            items=[AuditEventOut.model_validate(it) for it in items],
            next_cursor=next_cursor,
        )
