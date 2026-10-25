"""Repository for creating and querying immutable audit events."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import decode_cursor, encode_cursor
from app.core.redaction import redact
from app.core.request_context import get_request_id
from app.modules.audit.models import AuditEvent


class AuditRepository:
    """Append-only data access repository for audit trail."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record_audit_event(
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
        """Create and persist an append-only audit event with redacted metadata."""
        effective_req_id = request_id or get_request_id()
        safe_meta = redact(metadata or {})
        if not isinstance(safe_meta, dict):
            safe_meta = {"value": safe_meta}

        event = AuditEvent(
            id=uuid.uuid4(),
            org_id=org_id,
            actor_user_id=actor_user_id,
            actor_type=actor_type,
            action=action,
            target_type=target_type,
            target_id=target_id,
            request_id=effective_req_id,
            redacted_metadata=safe_meta,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def list_audit_events(
        self,
        *,
        org_id: UUID,
        action: str | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> tuple[list[AuditEvent], str | None]:
        """Query audit events for an organization with keyset pagination."""
        stmt = select(AuditEvent).where(AuditEvent.org_id == org_id)

        if action:
            stmt = stmt.where(AuditEvent.action == action)

        if cursor:
            payload = decode_cursor(cursor)
            stmt = stmt.where(
                tuple_(AuditEvent.created_at, AuditEvent.id) < (payload.created_at, payload.id)
            )

        stmt = stmt.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit + 1)

        result = await self.session.execute(stmt)
        rows: Sequence[AuditEvent] = result.scalars().all()

        has_next = len(rows) > limit
        selected = list(rows[:limit])

        next_cursor: str | None = None
        if has_next and selected:
            last = selected[-1]
            next_cursor = encode_cursor(last.created_at, last.id)

        return selected, next_cursor
