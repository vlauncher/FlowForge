"""Business logic for integration credentials and encrypted secret management."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt_secret
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.domain.permissions import Action, has_permission
from app.modules.audit.repository import AuditRepository
from app.modules.integrations.repository import IntegrationRepository
from app.modules.integrations.schemas import (
    CredentialCreateRequest,
    CredentialResponse,
    CredentialsPageResponse,
    RotateCredentialRequest,
)
from app.modules.organizations.repository import OrganizationRepository


class IntegrationService:
    """Manages write-only integration credentials with AES-256-GCM encryption."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = IntegrationRepository(session)
        self.org_repo = OrganizationRepository(session)

    async def create_credential(
        self,
        org_id: UUID,
        req: CredentialCreateRequest,
        *,
        user_id: UUID,
    ) -> CredentialResponse:
        """Encrypt secret at rest and save credential metadata."""
        member = await self.org_repo.get_membership(org_id=org_id, user_id=user_id)
        if not member:
            raise NotFoundError("Organization not found")

        if not has_permission(member.role, Action.CREDENTIAL_MANAGE):
            raise ForbiddenError(
                f"Role '{member.role}' lacks permission '{Action.CREDENTIAL_MANAGE}'"
            )

        # Check unique name within tenant
        existing = await self.repo.get_credential_by_name(req.name, org_id=org_id)
        if existing:
            raise ConflictError(f"Credential '{req.name}' already exists in this organization")

        # Encrypt secret at rest with active master key
        encrypted_secret, key_id = encrypt_secret(req.secret)

        cred = await self.repo.create_credential(
            org_id=org_id,
            name=req.name,
            provider=req.provider,
            encrypted_secret=encrypted_secret,
            key_id=key_id,
            allowed_hosts=req.allowed_hosts,
            permission_scopes=req.permission_scopes,
        )

        audit_repo = AuditRepository(self.session)
        await audit_repo.record_audit_event(
            org_id=org_id,
            actor_user_id=user_id,
            actor_type="user",
            action="credential.created",
            target_type="credential",
            target_id=cred.id,
            metadata={
                "name": req.name,
                "provider": req.provider,
                "allowed_hosts": req.allowed_hosts,
                "permission_scopes": req.permission_scopes,
            },
        )

        await self.session.commit()

        return CredentialResponse.model_validate(cred)

    async def list_credentials(
        self,
        org_id: UUID,
        *,
        user_id: UUID,
        limit: int = 50,
        cursor: str | None = None,
    ) -> CredentialsPageResponse:
        """List credential metadata (without secrets) for authorized callers."""
        member = await self.org_repo.get_membership(org_id=org_id, user_id=user_id)
        if not member:
            raise NotFoundError("Organization not found")

        if not has_permission(member.role, Action.CREDENTIAL_MANAGE):
            raise ForbiddenError(
                f"Role '{member.role}' lacks permission '{Action.CREDENTIAL_MANAGE}'"
            )

        rows, next_cursor = await self.repo.list_credentials_by_org(
            org_id=org_id,
            limit=limit,
            cursor=cursor,
        )

        return CredentialsPageResponse(
            items=[CredentialResponse.model_validate(r) for r in rows],
            next_cursor=next_cursor,
        )

    async def rotate_credential(
        self,
        org_id: UUID,
        credential_id: UUID,
        req: RotateCredentialRequest,
        *,
        user_id: UUID,
    ) -> CredentialResponse:
        """Rotate credential secret by re-encrypting with active master key."""
        member = await self.org_repo.get_membership(org_id=org_id, user_id=user_id)
        if not member:
            raise NotFoundError("Organization not found")

        if not has_permission(member.role, Action.CREDENTIAL_MANAGE):
            raise ForbiddenError(
                f"Role '{member.role}' lacks permission '{Action.CREDENTIAL_MANAGE}'"
            )

        cred = await self.repo.get_credential_by_id(credential_id, org_id=org_id)
        if not cred:
            raise NotFoundError(f"Credential '{credential_id}' not found")

        encrypted_secret, key_id = encrypt_secret(req.secret)
        cred.encrypted_secret = encrypted_secret
        cred.key_id = key_id
        cred.rotated_at = datetime.now(UTC)

        audit_repo = AuditRepository(self.session)
        await audit_repo.record_audit_event(
            org_id=org_id,
            actor_user_id=user_id,
            actor_type="user",
            action="credential.rotated",
            target_type="credential",
            target_id=cred.id,
            metadata={"name": cred.name, "provider": cred.provider, "key_id": key_id},
        )

        await self.session.commit()
        return CredentialResponse.model_validate(cred)
