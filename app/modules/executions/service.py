"""Business logic for workflow run triggering, concurrency checks, and tracking."""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

import jsonschema
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ConcurrencyLimitError,
    ForbiddenError,
    IdempotencyKeyReusedError,
    InvalidStateTransitionError,
    NotFoundError,
    ValidationError,
    VersionNotPublishedError,
)
from app.core.ids import new_id
from app.core.request_context import get_request_id
from app.domain.permissions import Action, has_permission
from app.domain.workflow_definition import canonical_json
from app.modules.audit.repository import AuditRepository
from app.modules.executions.models import OutboxEvent, WorkflowRun
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.schemas import (
    RunDetail,
    RunResponse,
    RunsPageResponse,
    RunSummary,
    StepAttemptResponse,
    StepAttemptsListResponse,
    TriggerRunRequest,
)
from app.modules.organizations.repository import OrganizationRepository
from app.modules.usage.budget import check_organization_budget
from app.modules.workflows.repository import WorkflowRepository
from app.observability.tracing import get_tracer, inject_trace_context


class ExecutionService:
    """Orchestrates workflow run triggering, idempotency, and status retrieval."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ExecutionRepository(session)
        self.workflow_repo = WorkflowRepository(session)
        self.org_repo = OrganizationRepository(session)

    async def trigger_run(
        self,
        workflow_id: UUID,
        req: TriggerRunRequest,
        *,
        user_id: UUID | None = None,
        trigger_kind: str = "manual",
        trigger_id: UUID | None = None,
        org_id: UUID | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[RunResponse, bool]:
        """Trigger a new workflow run with concurrency enforcement and idempotency.

        Returns (RunResponse, is_replayed).
        """
        # 1. Resolve workflow and verify permission
        if trigger_kind == "webhook":
            if org_id is None:
                raise ValueError("org_id is required for webhook runs")
            workflow = await self.workflow_repo.get_by_id(workflow_id, org_id=org_id)
            if not workflow:
                raise NotFoundError(f"Workflow '{workflow_id}' not found")
        else:
            if user_id is None:
                raise ValueError("user_id is required for manual runs")
            workflow_and_role = await self.workflow_repo.get_by_id_for_user(
                workflow_id, user_id=user_id
            )
            if not workflow_and_role:
                raise NotFoundError(f"Workflow '{workflow_id}' not found")
            workflow, caller_role = workflow_and_role

            if not has_permission(caller_role, Action.RUN_TRIGGER):
                raise ForbiddenError(
                    f"Role '{caller_role}' lacks permission '{Action.RUN_TRIGGER}'"
                )
            org_id = workflow.org_id

        if workflow.archived_at is not None:
            raise NotFoundError(f"Workflow '{workflow_id}' is archived")

        # 2. Resolve version
        if req.workflow_version is not None:
            version = await self.workflow_repo.get_version_by_number(
                workflow_id=workflow_id, version=req.workflow_version, org_id=org_id
            )
            if not version or version.status != "published":
                raise VersionNotPublishedError(
                    f"Workflow version {req.workflow_version} is not published"
                )
        else:
            if not workflow.current_version_id:
                raise VersionNotPublishedError("Workflow has no published versions")
            version = await self.workflow_repo.get_version_by_id(
                version_id=workflow.current_version_id, org_id=org_id
            )
            if not version or version.status != "published":
                raise VersionNotPublishedError("Workflow current version is not published")

        # 3. Validate inputs against inputs_schema
        definition_json = version.definition_json
        inputs_schema = definition_json.get("inputs_schema")
        if inputs_schema:
            validator = jsonschema.Draft202012Validator(inputs_schema)
            errors = sorted(validator.iter_errors(req.inputs), key=lambda e: str(e.path))
            if errors:
                err_list = [{"path": list(e.path), "message": e.message} for e in errors]
                raise ValidationError(
                    detail="Input payload failed schema validation",
                    errors=err_list,
                )

        # 4. Compute request fingerprint
        payload_to_fingerprint = {
            "version_id": str(version.id),
            "inputs": req.inputs,
        }
        request_fingerprint = hashlib.sha256(canonical_json(payload_to_fingerprint)).hexdigest()

        # 5. Idempotency check
        if idempotency_key:
            existing = await self.repo.get_run_by_idempotency_key(idempotency_key, org_id=org_id)
            if existing:
                existing_run, existing_version_num = existing
                if existing_run.request_fingerprint == request_fingerprint:
                    response = RunResponse(
                        run_id=existing_run.id,
                        state=existing_run.state,
                        workflow_id=existing_run.workflow_id,
                        workflow_version=existing_version_num,
                        version_id=existing_run.version_id,
                        status_url=f"/v1/runs/{existing_run.id}",
                        created_at=existing_run.created_at,
                    )
                    return response, True
                else:
                    raise IdempotencyKeyReusedError(
                        "Idempotency key has already been used with different "
                        "request inputs or version"
                    )

        # 6. Concurrency check with pessimistic row lock
        max_concurrent = await self.repo.lock_organization_for_concurrency(org_id=org_id)
        limit = max_concurrent if max_concurrent is not None else 5
        active_count = await self.repo.count_active_runs(org_id=org_id)
        if active_count >= limit:
            raise ConcurrencyLimitError(
                f"Organization active run concurrency limit ({limit}) reached"
            )

        # Budget check under pessimistic lock
        await check_organization_budget(self.session, org_id=org_id)

        # 7. Create WorkflowRun and OutboxEvent with distributed trace context
        run_id = new_id()
        start_step = definition_json.get("start")
        run = WorkflowRun(
            id=run_id,
            org_id=org_id,
            workflow_id=workflow.id,
            version_id=version.id,
            state="QUEUED",
            trigger_kind=trigger_kind,
            trigger_id=trigger_id,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            inputs=req.inputs,
            context={},
            current_step_id=start_step,
            attempt_epoch=0,
            created_by=user_id,
        )

        tracer = get_tracer()
        with tracer.start_as_current_span("api.trigger_run") as span:
            span.set_attribute("flowforge.run_id", str(run_id))
            span.set_attribute("flowforge.workflow_id", str(workflow.id))
            span.set_attribute("flowforge.org_id", str(org_id))
            carrier: dict[str, str] = {}
            inject_trace_context(carrier)

            outbox = OutboxEvent(
                aggregate_type="run",
                aggregate_id=run_id,
                event_type="RunRequested",
                schema_version=1,
                payload={
                    "run_id": str(run_id),
                    "org_id": str(org_id),
                    "request_id": get_request_id() or "",
                    "trace_context": carrier,
                },
            )

        await self.repo.create_run_and_outbox(run, outbox, org_id=org_id)

        audit_repo = AuditRepository(self.session)
        audit_metadata: dict[str, Any] = {
            "workflow_id": str(workflow.id),
            "version_id": str(version.id),
        }
        if trigger_id:
            audit_metadata["trigger_id"] = str(trigger_id)

        await audit_repo.record_audit_event(
            org_id=org_id,
            actor_user_id=user_id,
            actor_type="webhook" if trigger_kind == "webhook" else "user",
            action="run.triggered",
            target_type="run",
            target_id=run.id,
            metadata=audit_metadata,
        )

        await self.session.commit()

        response = RunResponse(
            run_id=run.id,
            state=run.state,
            workflow_id=run.workflow_id,
            workflow_version=version.version,
            version_id=run.version_id,
            status_url=f"/v1/runs/{run.id}",
            created_at=run.created_at,
        )
        return response, False

    async def get_run_detail(self, run_id: UUID, *, user_id: UUID) -> RunDetail:
        """Retrieve full details of a run for an authorized organization member."""
        run_data = await self.repo.get_by_id_for_user(run_id, user_id=user_id)
        if not run_data:
            raise NotFoundError("Workflow run not found")

        run, version_num, caller_role = run_data
        if not has_permission(caller_role, Action.RUN_READ):
            raise ForbiddenError(f"Role '{caller_role}' lacks permission '{Action.RUN_READ}'")

        return RunDetail(
            id=run.id,
            org_id=run.org_id,
            workflow_id=run.workflow_id,
            workflow_version=version_num,
            version_id=run.version_id,
            state=run.state,
            trigger_kind=run.trigger_kind,
            current_step_id=run.current_step_id,
            started_at=run.started_at,
            finished_at=run.finished_at,
            created_at=run.created_at,
            inputs=run.inputs,
            outputs=run.outputs,
            context=run.context,
            error_code=run.error_code,
            error_detail=run.error_detail,
            cancel_requested=run.cancel_requested,
            status_url=f"/v1/runs/{run.id}",
        )

    async def list_step_attempts(self, run_id: UUID, *, user_id: UUID) -> StepAttemptsListResponse:
        """List step attempts for a run if caller is authorized."""
        run_data = await self.repo.get_by_id_for_user(run_id, user_id=user_id)
        if not run_data:
            raise NotFoundError("Workflow run not found")

        run, _, caller_role = run_data
        if not has_permission(caller_role, Action.RUN_READ):
            raise ForbiddenError(f"Role '{caller_role}' lacks permission '{Action.RUN_READ}'")

        attempts = await self.repo.list_step_attempts(run_id, org_id=run.org_id)
        return StepAttemptsListResponse(
            items=[StepAttemptResponse.model_validate(att) for att in attempts]
        )

    async def list_runs_by_org(
        self,
        org_id: UUID,
        *,
        user_id: UUID,
        limit: int = 50,
        cursor: str | None = None,
        state: str | None = None,
        workflow_id: UUID | None = None,
    ) -> RunsPageResponse:
        """List runs within an organization with cursor pagination."""
        member = await self.org_repo.get_membership(org_id=org_id, user_id=user_id)
        if not member:
            raise NotFoundError("Organization not found")

        if not has_permission(member.role, Action.RUN_READ):
            raise ForbiddenError(f"Role '{member.role}' lacks permission '{Action.RUN_READ}'")

        rows, next_cursor = await self.repo.list_runs_by_org(
            org_id=org_id,
            limit=limit,
            cursor=cursor,
            state=state,
            workflow_id=workflow_id,
        )

        summaries = [
            RunSummary(
                id=run.id,
                org_id=run.org_id,
                workflow_id=run.workflow_id,
                workflow_version=version_num,
                version_id=run.version_id,
                state=run.state,
                trigger_kind=run.trigger_kind,
                current_step_id=run.current_step_id,
                started_at=run.started_at,
                finished_at=run.finished_at,
                created_at=run.created_at,
            )
            for run, version_num in rows
        ]

        return RunsPageResponse(items=summaries, next_cursor=next_cursor)

    async def cancel_run(
        self,
        run_id: UUID,
        *,
        user_id: UUID,
    ) -> RunDetail:
        """Cancel a workflow run."""
        res = await self.repo.get_by_id_for_user(run_id, user_id=user_id)
        if not res:
            raise NotFoundError("Workflow run not found")
        run, version_num, role = res

        if not has_permission(role, Action.RUN_CANCEL):
            raise ForbiddenError(f"Role '{role}' lacks permission '{Action.RUN_CANCEL}'")

        cancelled = await self.repo.cancel_run(run_id, org_id=run.org_id)
        if not cancelled:
            raise InvalidStateTransitionError("Run cannot be cancelled in its current state")

        audit_repo = AuditRepository(self.session)
        await audit_repo.record_audit_event(
            org_id=run.org_id,
            actor_user_id=user_id,
            actor_type="user",
            action="run.cancelled",
            target_type="run",
            target_id=run.id,
            metadata={"previous_state": run.state},
        )

        await self.session.commit()

        updated_run, updated_version_num = cancelled
        return RunDetail(
            id=updated_run.id,
            org_id=updated_run.org_id,
            workflow_id=updated_run.workflow_id,
            workflow_version=updated_version_num,
            version_id=updated_run.version_id,
            state=updated_run.state,
            trigger_kind=updated_run.trigger_kind,
            current_step_id=updated_run.current_step_id,
            inputs=updated_run.inputs or {},
            outputs=updated_run.outputs,
            context=updated_run.context or {},
            error_code=updated_run.error_code,
            error_detail=updated_run.error_detail,
            cancel_requested=updated_run.cancel_requested,
            status_url=f"/v1/runs/{updated_run.id}",
            started_at=updated_run.started_at,
            finished_at=updated_run.finished_at,
            created_at=updated_run.created_at,
        )

    async def retry_run(
        self,
        run_id: UUID,
        *,
        user_id: UUID,
    ) -> RunDetail:
        """Retry a failed workflow run."""
        res = await self.repo.get_by_id_for_user(run_id, user_id=user_id)
        if not res:
            raise NotFoundError("Workflow run not found")
        run, version_num, role = res

        if not has_permission(role, Action.RUN_RETRY):
            raise ForbiddenError(f"Role '{role}' lacks permission '{Action.RUN_RETRY}'")

        # Concurrency check
        max_concurrent = await self.repo.lock_organization_for_concurrency(org_id=run.org_id)
        limit = max_concurrent if max_concurrent is not None else 5
        active_count = await self.repo.count_active_runs(org_id=run.org_id)
        if active_count >= limit:
            raise ConcurrencyLimitError(
                f"Organization active run concurrency limit ({limit}) reached"
            )

        retried = await self.repo.retry_run(run_id, org_id=run.org_id)
        if not retried:
            raise InvalidStateTransitionError("Run is not in FAILED state and cannot be retried")

        audit_repo = AuditRepository(self.session)
        await audit_repo.record_audit_event(
            org_id=run.org_id,
            actor_user_id=user_id,
            actor_type="user",
            action="run.retried",
            target_type="run",
            target_id=run.id,
            metadata={"previous_state": "FAILED"},
        )

        await self.session.commit()

        updated_run, updated_version_num = retried
        return RunDetail(
            id=updated_run.id,
            org_id=updated_run.org_id,
            workflow_id=updated_run.workflow_id,
            workflow_version=updated_version_num,
            version_id=updated_run.version_id,
            state=updated_run.state,
            trigger_kind=updated_run.trigger_kind,
            current_step_id=updated_run.current_step_id,
            inputs=updated_run.inputs or {},
            outputs=updated_run.outputs,
            context=updated_run.context or {},
            error_code=updated_run.error_code,
            error_detail=updated_run.error_detail,
            cancel_requested=updated_run.cancel_requested,
            status_url=f"/v1/runs/{updated_run.id}",
            started_at=updated_run.started_at,
            finished_at=updated_run.finished_at,
            created_at=updated_run.created_at,
        )
