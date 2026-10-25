"""Database repository for tenant integration credentials and tool effect ledgers."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import and_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import decode_cursor, encode_cursor
from app.modules.integrations.models import IntegrationCredential, ToolEffect


class IntegrationRepository:
    """Encapsulates tenant-isolated database access for integration credentials and tool effects."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_credential(
        self,
        *,
        org_id: UUID,
        name: str,
        provider: str,
        encrypted_secret: bytes,
        key_id: str,
        allowed_hosts: list[str],
        permission_scopes: list[str],
    ) -> IntegrationCredential:
        """Insert a newly encrypted credential row."""
        cred = IntegrationCredential(
            org_id=org_id,
            name=name.strip(),
            provider=provider.strip(),
            encrypted_secret=encrypted_secret,
            key_id=key_id,
            allowed_hosts=allowed_hosts,
            permission_scopes=permission_scopes,
        )
        self.session.add(cred)
        await self.session.flush()
        return cred

    async def get_credential_by_id(
        self,
        credential_id: UUID,
        *,
        org_id: UUID,
    ) -> IntegrationCredential | None:
        """Fetch credential strictly scoped to organization."""
        stmt = select(IntegrationCredential).where(
            and_(
                IntegrationCredential.id == credential_id,
                IntegrationCredential.org_id == org_id,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_credential_by_name(
        self,
        name: str,
        *,
        org_id: UUID,
    ) -> IntegrationCredential | None:
        """Fetch credential by unique name within organization."""
        stmt = select(IntegrationCredential).where(
            and_(
                IntegrationCredential.name == name.strip(),
                IntegrationCredential.org_id == org_id,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_credentials_by_org(
        self,
        *,
        org_id: UUID,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[list[IntegrationCredential], str | None]:
        """List credentials for an organization with keyset cursor pagination."""
        stmt = select(IntegrationCredential).where(IntegrationCredential.org_id == org_id)

        if cursor:
            payload = decode_cursor(cursor)
            stmt = stmt.where(
                tuple_(IntegrationCredential.created_at, IntegrationCredential.id)
                < (payload.created_at, payload.id)
            )

        stmt = stmt.order_by(
            IntegrationCredential.created_at.desc(), IntegrationCredential.id.desc()
        ).limit(limit + 1)

        result = await self.session.execute(stmt)
        rows: Sequence[IntegrationCredential] = result.scalars().all()

        has_next = len(rows) > limit
        selected = list(rows[:limit])

        next_cursor: str | None = None
        if has_next and selected:
            last = selected[-1]
            next_cursor = encode_cursor(last.created_at, last.id)

        return selected, next_cursor

    async def get_tool_effect(
        self,
        provider: str,
        idempotency_key: str,
        *,
        org_id: UUID,
    ) -> ToolEffect | None:
        """Fetch tool effect ledger entry for provider and idempotency key."""
        stmt = select(ToolEffect).where(
            and_(
                ToolEffect.org_id == org_id,
                ToolEffect.provider == provider,
                ToolEffect.idempotency_key == idempotency_key,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_tool_effect_intended(
        self,
        *,
        org_id: UUID,
        run_id: UUID,
        step_id: str,
        provider: str,
        idempotency_key: str,
        request_hash: str,
    ) -> ToolEffect:
        """Record or update INTENDED state before opening network socket."""
        effect = await self.get_tool_effect(provider, idempotency_key, org_id=org_id)
        if effect:
            effect.state = "INTENDED"
            effect.request_hash = request_hash
        else:
            effect = ToolEffect(
                org_id=org_id,
                run_id=run_id,
                step_id=step_id,
                provider=provider,
                idempotency_key=idempotency_key,
                state="INTENDED",
                request_hash=request_hash,
            )
            self.session.add(effect)
        await self.session.flush()
        return effect
