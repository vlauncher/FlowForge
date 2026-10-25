"""Database repository for workflows and version records."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import CursorPayload
from app.modules.organizations.models import Membership
from app.modules.workflows.models import Workflow, WorkflowVersion


class WorkflowRepository:
    """Encapsulates database access for tenant-isolated workflows and versions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_workflow(
        self,
        *,
        org_id: UUID,
        display_name: str,
        description: str | None,
        created_by: UUID,
    ) -> Workflow:
        """Insert a new workflow within an organization."""
        wf = Workflow(
            org_id=org_id,
            display_name=display_name.strip(),
            description=description.strip() if description else None,
            created_by=created_by,
        )
        self.session.add(wf)
        await self.session.flush()
        return wf

    async def get_by_id(
        self,
        workflow_id: UUID,
        *,
        org_id: UUID,
    ) -> Workflow | None:
        """Retrieve workflow strictly scoped to the tenant organization."""
        stmt = select(Workflow).where(
            and_(
                Workflow.id == workflow_id,
                Workflow.org_id == org_id,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_for_update(
        self,
        workflow_id: UUID,
        *,
        org_id: UUID,
    ) -> Workflow | None:
        """Retrieve workflow with exclusive row-level lock (FOR UPDATE)."""
        stmt = (
            select(Workflow)
            .where(
                and_(
                    Workflow.id == workflow_id,
                    Workflow.org_id == org_id,
                )
            )
            .with_for_update()
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_for_user(
        self,
        workflow_id: UUID,
        *,
        user_id: UUID,
    ) -> tuple[Workflow, str] | None:
        """Retrieve workflow joined with the caller's membership in a single query."""
        stmt = (
            select(Workflow, Membership.role)
            .join(
                Membership,
                and_(
                    Membership.org_id == Workflow.org_id,
                    Membership.user_id == user_id,
                ),
            )
            .where(Workflow.id == workflow_id)
        )
        result = await self.session.execute(stmt)
        row = result.first()
        if not row:
            return None
        return row[0], row[1]

    async def list_workflows(
        self,
        *,
        org_id: UUID,
        include_archived: bool,
        cursor: CursorPayload | None,
        limit: int,
    ) -> tuple[Sequence[Workflow], bool]:
        """List organization workflows with keyset pagination."""
        stmt = select(Workflow).where(Workflow.org_id == org_id)

        if not include_archived:
            stmt = stmt.where(Workflow.archived_at.is_(None))

        if cursor:
            stmt = stmt.where(
                tuple_(Workflow.created_at, Workflow.id) < tuple_(cursor.created_at, cursor.id)
            )

        stmt = stmt.order_by(Workflow.created_at.desc(), Workflow.id.desc()).limit(limit + 1)
        result = await self.session.execute(stmt)
        items = result.scalars().all()
        has_more = len(items) > limit
        return items[:limit], has_more

    # -----------------------------------------------------------------------
    # Version Management Methods (Phase 3)
    # -----------------------------------------------------------------------

    async def get_draft_version(
        self,
        workflow_id: UUID,
        *,
        org_id: UUID,
    ) -> WorkflowVersion | None:
        """Retrieve the current draft version for a workflow if one exists."""
        stmt = select(WorkflowVersion).where(
            and_(
                WorkflowVersion.workflow_id == workflow_id,
                WorkflowVersion.org_id == org_id,
                WorkflowVersion.status == "draft",
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_version_number(
        self,
        workflow_id: UUID,
        *,
        org_id: UUID,
    ) -> int:
        """Return the highest version number created for this workflow (or 0 if none)."""
        stmt = select(func.coalesce(func.max(WorkflowVersion.version), 0)).where(
            and_(
                WorkflowVersion.workflow_id == workflow_id,
                WorkflowVersion.org_id == org_id,
            )
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def create_version_draft(
        self,
        *,
        org_id: UUID,
        workflow_id: UUID,
        version: int,
        definition_json: dict[str, Any],
        schema_version: int = 1,
        created_by: UUID | None,
    ) -> WorkflowVersion:
        """Insert a new draft version record."""
        ver = WorkflowVersion(
            workflow_id=workflow_id,
            org_id=org_id,
            version=version,
            status="draft",
            definition_json=definition_json,
            schema_version=schema_version,
            checksum=None,
            created_by=created_by,
        )
        self.session.add(ver)
        await self.session.flush()
        return ver

    async def update_version_draft(
        self,
        *,
        org_id: UUID,
        workflow_id: UUID,
        version: int,
        definition_json: dict[str, Any],
    ) -> WorkflowVersion | None:
        """Update an existing draft version in place."""
        stmt = select(WorkflowVersion).where(
            and_(
                WorkflowVersion.workflow_id == workflow_id,
                WorkflowVersion.org_id == org_id,
                WorkflowVersion.version == version,
                WorkflowVersion.status == "draft",
            )
        )
        result = await self.session.execute(stmt)
        ver = result.scalar_one_or_none()
        if not ver:
            return None
        ver.definition_json = definition_json
        await self.session.flush()
        return ver

    async def list_versions(
        self,
        *,
        org_id: UUID,
        workflow_id: UUID,
        cursor: CursorPayload | None,
        limit: int,
    ) -> tuple[Sequence[WorkflowVersion], bool]:
        """List versions of a workflow ordered by version descending."""
        stmt = select(WorkflowVersion).where(
            and_(
                WorkflowVersion.workflow_id == workflow_id,
                WorkflowVersion.org_id == org_id,
            )
        )

        if cursor:
            stmt = stmt.where(
                tuple_(WorkflowVersion.created_at, WorkflowVersion.id)
                < tuple_(cursor.created_at, cursor.id)
            )

        stmt = stmt.order_by(WorkflowVersion.created_at.desc(), WorkflowVersion.id.desc()).limit(
            limit + 1
        )
        result = await self.session.execute(stmt)
        items = result.scalars().all()
        has_more = len(items) > limit
        return items[:limit], has_more

    async def get_version_by_number(
        self,
        *,
        org_id: UUID,
        workflow_id: UUID,
        version: int,
    ) -> WorkflowVersion | None:
        """Retrieve a specific version by its version integer."""
        stmt = select(WorkflowVersion).where(
            and_(
                WorkflowVersion.workflow_id == workflow_id,
                WorkflowVersion.org_id == org_id,
                WorkflowVersion.version == version,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_version_by_id(
        self,
        *,
        org_id: UUID,
        version_id: UUID,
    ) -> WorkflowVersion | None:
        """Retrieve a specific version by primary key."""
        stmt = select(WorkflowVersion).where(
            and_(
                WorkflowVersion.id == version_id,
                WorkflowVersion.org_id == org_id,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def publish_version(
        self,
        *,
        org_id: UUID,
        workflow: Workflow,
        version: WorkflowVersion,
        checksum: str,
    ) -> WorkflowVersion:
        """Mark version published and update workflow current_version_id in one transaction."""
        now = datetime.now(UTC)
        version.status = "published"
        version.checksum = checksum
        version.published_at = now

        workflow.current_version_id = version.id
        workflow.updated_at = now

        await self.session.flush()
        return version
