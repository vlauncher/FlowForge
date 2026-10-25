"""Database repository for triggers."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.modules.integrations.models import IntegrationCredential
from app.modules.triggers.models import Trigger


class TriggerRepository:
    """Manages persistence of triggers strictly adhering to tenancy boundaries."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_trigger(
        self,
        *,
        workflow_id: UUID,
        credential_id: UUID,
        org_id: UUID,
        kind: str = "webhook",
    ) -> Trigger:
        """Create a new trigger for a workflow."""
        trigger = Trigger(
            id=new_id(),
            org_id=org_id,
            workflow_id=workflow_id,
            credential_id=credential_id,
            kind=kind,
            enabled=True,
        )
        self.session.add(trigger)
        await self.session.flush()
        return trigger

    async def get_by_id(
        self,
        trigger_id: UUID,
        *,
        org_id: UUID,
    ) -> Trigger | None:
        """Fetch trigger by id strictly scoped to org_id."""
        stmt = select(Trigger).where(Trigger.id == trigger_id, Trigger.org_id == org_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_trigger_with_credential(
        self,
        trigger_id: UUID,
    ) -> tuple[Trigger, IntegrationCredential] | None:
        """Fetch active trigger and its associated credential for webhook signature verification."""
        stmt = (
            select(Trigger, IntegrationCredential)
            .join(IntegrationCredential, Trigger.credential_id == IntegrationCredential.id)
            .where(
                Trigger.id == trigger_id,
                Trigger.enabled.is_(True),
            )
        )
        result = await self.session.execute(stmt)
        row = result.first()
        if not row:
            return None
        return row[0], row[1]

    async def list_by_workflow(
        self,
        workflow_id: UUID,
        *,
        org_id: UUID,
    ) -> list[Trigger]:
        """List triggers for a specific workflow scoped to org_id."""
        stmt = (
            select(Trigger)
            .where(
                Trigger.workflow_id == workflow_id,
                Trigger.org_id == org_id,
            )
            .order_by(Trigger.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
