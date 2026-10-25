"""Business logic for workflow authoring, versions, and validation."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    AppError,
    DraftExistsError,
    InvalidStateTransitionError,
    NotFoundError,
)
from app.core.pagination import Page, decode_cursor, encode_cursor
from app.domain.graph_validator import validate_definition
from app.domain.workflow_definition import definition_checksum
from app.modules.audit.repository import AuditRepository
from app.modules.workflows.repository import WorkflowRepository
from app.modules.workflows.schemas import (
    ValidationIssueSchema,
    WorkflowCreateRequest,
    WorkflowPublishRequest,
    WorkflowResponse,
    WorkflowValidateRequest,
    WorkflowValidateResponse,
    WorkflowVersionCreateRequest,
    WorkflowVersionResponse,
    WorkflowVersionSummaryResponse,
    WorkflowVersionUpdateRequest,
)


class WorkflowService:
    """Orchestrates workflow creation, retrieval, versioning, and validation."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = WorkflowRepository(session)

    async def create_workflow(
        self,
        *,
        org_id: UUID,
        req: WorkflowCreateRequest,
        user_id: UUID,
    ) -> WorkflowResponse:
        """Create a new workflow shell in the organization."""
        wf = await self.repo.create_workflow(
            org_id=org_id,
            display_name=req.display_name,
            description=req.description,
            created_by=user_id,
        )
        await self.session.commit()
        return WorkflowResponse.model_validate(wf)

    async def list_workflows(
        self,
        *,
        org_id: UUID,
        include_archived: bool = False,
        limit: int = 20,
        cursor: str | None = None,
    ) -> Page[WorkflowResponse]:
        """List workflows for an organization with keyset pagination."""
        parsed_cursor = decode_cursor(cursor) if cursor else None
        items, has_more = await self.repo.list_workflows(
            org_id=org_id,
            include_archived=include_archived,
            cursor=parsed_cursor,
            limit=limit,
        )

        responses = [WorkflowResponse.model_validate(w) for w in items]
        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = encode_cursor(last.created_at, last.id)

        return Page(items=responses, next_cursor=next_cursor, has_more=has_more)

    async def get_workflow_for_user(
        self,
        workflow_id: UUID,
        *,
        user_id: UUID,
    ) -> WorkflowResponse:
        """Retrieve a workflow asserting caller has active membership in its tenant organization."""
        result = await self.repo.get_by_id_for_user(workflow_id, user_id=user_id)
        if not result:
            raise NotFoundError("Workflow not found")

        wf, _role = result
        return WorkflowResponse.model_validate(wf)

    # -----------------------------------------------------------------------
    # Versioning & Publishing (Phase 3)
    # -----------------------------------------------------------------------

    async def create_version_draft(
        self,
        *,
        org_id: UUID,
        workflow_id: UUID,
        user_id: UUID,
        req: WorkflowVersionCreateRequest,
    ) -> WorkflowVersionResponse:
        """Create a new draft version for a workflow."""
        wf = await self.repo.get_by_id(workflow_id, org_id=org_id)
        if not wf:
            raise NotFoundError("Workflow not found")

        existing_draft = await self.repo.get_draft_version(workflow_id, org_id=org_id)
        if existing_draft:
            raise DraftExistsError("A draft version already exists for this workflow")

        # Resolve definition
        definition_to_use: dict[str, Any] = req.definition
        if req.from_version:
            from_ver = await self.repo.get_version_by_number(
                org_id=org_id, workflow_id=workflow_id, version=req.from_version
            )
            if not from_ver:
                raise NotFoundError(f"Version {req.from_version} not found")
            if not definition_to_use:
                definition_to_use = from_ver.definition_json

        latest_version = await self.repo.get_latest_version_number(workflow_id, org_id=org_id)
        next_version = latest_version + 1

        version = await self.repo.create_version_draft(
            org_id=org_id,
            workflow_id=workflow_id,
            version=next_version,
            definition_json=definition_to_use,
            schema_version=1,
            created_by=user_id,
        )
        await self.session.commit()
        return WorkflowVersionResponse.model_validate(version)

    async def update_version_draft(
        self,
        *,
        org_id: UUID,
        workflow_id: UUID,
        version_num: int,
        req: WorkflowVersionUpdateRequest,
    ) -> WorkflowVersionResponse:
        """Update an existing draft version definition in place."""
        wf = await self.repo.get_by_id(workflow_id, org_id=org_id)
        if not wf:
            raise NotFoundError("Workflow not found")

        version = await self.repo.get_version_by_number(
            org_id=org_id, workflow_id=workflow_id, version=version_num
        )
        if not version:
            raise NotFoundError(f"Version {version_num} not found")

        if version.status == "published":
            raise InvalidStateTransitionError(
                "Published versions are immutable and cannot be updated"
            )

        updated = await self.repo.update_version_draft(
            org_id=org_id,
            workflow_id=workflow_id,
            version=version_num,
            definition_json=req.definition,
        )
        if not updated:
            raise NotFoundError("Draft version not found")

        await self.session.commit()
        return WorkflowVersionResponse.model_validate(updated)

    async def list_versions(
        self,
        *,
        org_id: UUID,
        workflow_id: UUID,
        limit: int = 20,
        cursor: str | None = None,
    ) -> Page[WorkflowVersionSummaryResponse]:
        """List versions of a workflow."""
        wf = await self.repo.get_by_id(workflow_id, org_id=org_id)
        if not wf:
            raise NotFoundError("Workflow not found")

        parsed_cursor = decode_cursor(cursor) if cursor else None
        items, has_more = await self.repo.list_versions(
            org_id=org_id,
            workflow_id=workflow_id,
            cursor=parsed_cursor,
            limit=limit,
        )

        responses = [WorkflowVersionSummaryResponse.model_validate(v) for v in items]
        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = encode_cursor(last.created_at, last.id)

        return Page(items=responses, next_cursor=next_cursor, has_more=has_more)

    async def get_version(
        self,
        *,
        org_id: UUID,
        workflow_id: UUID,
        version_num: int,
    ) -> WorkflowVersionResponse:
        """Retrieve full details of a specific workflow version."""
        wf = await self.repo.get_by_id(workflow_id, org_id=org_id)
        if not wf:
            raise NotFoundError("Workflow not found")

        version = await self.repo.get_version_by_number(
            org_id=org_id, workflow_id=workflow_id, version=version_num
        )
        if not version:
            raise NotFoundError(f"Version {version_num} not found")

        return WorkflowVersionResponse.model_validate(version)

    async def validate_workflow(
        self,
        *,
        org_id: UUID,
        workflow_id: UUID,
        req: WorkflowValidateRequest,
    ) -> WorkflowValidateResponse:
        """Run pure graph validator against provided workflow definition."""
        wf = await self.repo.get_by_id(workflow_id, org_id=org_id)
        if not wf:
            raise NotFoundError("Workflow not found")

        issues = validate_definition(req.definition)
        is_valid = len(issues) == 0
        checksum = definition_checksum(req.definition) if is_valid else None

        errors = [
            ValidationIssueSchema(
                code=i.code,
                field=i.field,
                message=i.message,
                step_ids=i.step_ids,
            )
            for i in issues
        ]

        return WorkflowValidateResponse(valid=is_valid, checksum=checksum, errors=errors)

    async def publish_workflow(
        self,
        *,
        org_id: UUID,
        workflow_id: UUID,
        req: WorkflowPublishRequest,
    ) -> WorkflowVersionResponse:
        """Publish a workflow version in an exclusive transaction."""
        wf = await self.repo.get_for_update(workflow_id, org_id=org_id)
        if not wf:
            raise NotFoundError("Workflow not found")

        if wf.archived_at is not None:
            raise InvalidStateTransitionError("Cannot publish version on an archived workflow")

        if req.version is not None:
            target_version = await self.repo.get_version_by_number(
                org_id=org_id, workflow_id=workflow_id, version=req.version
            )
        else:
            target_version = await self.repo.get_draft_version(workflow_id, org_id=org_id)

        if not target_version:
            raise NotFoundError("Target version for publication not found")

        if target_version.status == "published":
            raise InvalidStateTransitionError("Workflow version is already published")

        # Execute pure graph validator
        issues = validate_definition(target_version.definition_json)
        if issues:
            first = issues[0]
            error_list = [
                {"code": i.code, "field": i.field, "message": i.message, "step_ids": i.step_ids}
                for i in issues
            ]
            raise AppError(
                code=first.code,
                status=422,
                title="Graph Validation Failed",
                detail=first.message,
                errors=error_list,
            )

        checksum = definition_checksum(target_version.definition_json)
        published_version = await self.repo.publish_version(
            org_id=org_id,
            workflow=wf,
            version=target_version,
            checksum=checksum,
        )

        audit_repo = AuditRepository(self.session)
        await audit_repo.record_audit_event(
            org_id=org_id,
            actor_user_id=published_version.created_by,
            actor_type="user",
            action="workflow.published",
            target_type="workflow",
            target_id=workflow_id,
            metadata={
                "version": published_version.version,
                "version_id": str(published_version.id),
                "checksum": published_version.checksum,
            },
        )

        await self.session.commit()
        return WorkflowVersionResponse.model_validate(published_version)
