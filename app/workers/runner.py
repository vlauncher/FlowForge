"""Durable workflow execution runner with lease claiming, heartbeat, and epoch fencing."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import socket
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from opentelemetry import trace
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.executor import execute_ai_step
from app.ai.interface import LLMClient
from app.core.config import get_settings
from app.core.errors import BudgetExceededError
from app.core.ids import new_id
from app.domain.graph_validator import compute_dominators
from app.domain.template_engine import (
    TemplateResolutionError,
    build_scope,
    evaluate_condition,
    resolve_value,
)
from app.domain.workflow_definition import ConditionConfig
from app.infrastructure.db.session import get_session_factory
from app.infrastructure.http_tool.adapter import execute_http_step
from app.infrastructure.http_tool.backoff import compute_backoff_seconds
from app.modules.approvals.models import ApprovalRequest
from app.modules.executions.models import OutboxEvent, StepAttempt, WorkflowRun
from app.modules.integrations.models import IntegrationCredential
from app.modules.usage.budget import reserve_budget, settle_budget
from app.modules.workflows.models import WorkflowVersion
from app.observability.metrics import RUNS_TOTAL, STEP_ATTEMPTS_TOTAL
from app.observability.tracing import extract_trace_context, get_tracer

logger = logging.getLogger("flowforge.workers.runner")

MAX_STEPS_PER_RUN = 100
REDACT_REGEX = re.compile(r"(?i)(password|secret|token|authorization|api[_-]?key|cookie)")


def redact(val: Any) -> Any:
    """Recursively mask sensitive values matching security rules."""
    if isinstance(val, dict):
        return {k: ("***" if REDACT_REGEX.search(k) else redact(v)) for k, v in val.items()}
    if isinstance(val, list):
        return [redact(item) for item in val]
    return val


def get_worker_id() -> str:
    """Generate a unique identity for the current worker process."""
    return f"{socket.gethostname()}-{os.getpid()}-{id(asyncio.current_task())}"


async def _heartbeat_loop(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: UUID,
    epoch: int,
    lease_seconds: int,
    interval_seconds: int,
    stop_event: asyncio.Event,
    fenced_event: asyncio.Event,
) -> None:
    """Periodically renew lease. If rowcount is 0, signal fencing event."""
    while not stop_event.is_set():
        try:
            await asyncio.sleep(interval_seconds)
            if stop_event.is_set():
                break

            async with session_factory() as session:
                async with session.begin():
                    stmt = text("""
                        UPDATE workflow_runs
                        SET lease_expires_at = now() + :lease_interval,
                            heartbeat_at = now(),
                            updated_at = now()
                        WHERE id = :run_id AND state = 'RUNNING' AND attempt_epoch = :epoch
                    """)
                    result = await session.execute(
                        stmt,
                        {
                            "run_id": run_id,
                            "lease_interval": timedelta(seconds=lease_seconds),
                            "epoch": epoch,
                        },
                    )
                    rowcount = getattr(result, "rowcount", 0)
                    if rowcount == 0:
                        logger.warning(
                            "Worker fenced during heartbeat for run %s (epoch %d)", run_id, epoch
                        )
                        fenced_event.set()
                        break
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Heartbeat error for run %s: %s", run_id, exc)


async def execute_run(
    run_id: UUID,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    worker_id: str | None = None,
    http_client: httpx.AsyncClient | None = None,
    llm_client: LLMClient | None = None,
) -> None:
    """Claim and execute a workflow run until terminal, paused, or fenced."""
    factory = session_factory or get_session_factory()
    settings = get_settings()
    w_id = worker_id or get_worker_id()
    lease_secs = settings.lease_seconds
    heartbeat_secs = settings.heartbeat_seconds

    # 1. Claim run
    claim_sql = text("""
        UPDATE workflow_runs
        SET state = 'RUNNING',
            lease_owner = :worker_id,
            lease_expires_at = now() + :lease_interval,
            heartbeat_at = now(),
            attempt_epoch = attempt_epoch + 1,
            started_at = COALESCE(started_at, now()),
            updated_at = now()
        WHERE id = :run_id
          AND (
            (state = 'QUEUED' AND (next_attempt_at IS NULL OR next_attempt_at <= now()))
            OR (state = 'RUNNING' AND lease_expires_at < now())
          )
        RETURNING id, org_id, version_id, current_step_id, inputs, context,
                  attempt_epoch, cancel_requested;
    """)

    async with factory() as session:
        async with session.begin():
            res = await session.execute(
                claim_sql,
                {
                    "run_id": run_id,
                    "worker_id": w_id,
                    "lease_interval": timedelta(seconds=lease_secs),
                },
            )
            claimed = res.mappings().first()

    if not claimed:
        # Run already running with valid lease, or already finished (idempotent no-op)
        logger.info("Claim skipped for run %s (not claimable)", run_id)
        return

    org_id: UUID = claimed["org_id"]
    version_id: UUID = claimed["version_id"]
    current_step_id: str | None = claimed["current_step_id"]
    inputs: dict[str, Any] = claimed["inputs"] or {}
    context: dict[str, Any] = dict(claimed["context"] or {})
    epoch: int = claimed["attempt_epoch"]

    # 2. Fetch definition
    async with factory() as session:
        v_res = await session.execute(
            select(WorkflowVersion).where(WorkflowVersion.id == version_id)
        )
        version_obj = v_res.scalar_one_or_none()
        if not version_obj:
            logger.error("Version %s not found for run %s", version_id, run_id)
            return
        definition_json = version_obj.definition_json

    steps_by_id = {s["id"]: s for s in definition_json.get("steps", [])}
    if not current_step_id:
        current_step_id = definition_json.get("start")

    # Extract distributed trace context from OutboxEvent
    carrier = None
    async with factory() as session:
        ob_res = await session.execute(
            select(OutboxEvent.payload)
            .where(OutboxEvent.aggregate_id == run_id)
            .order_by(OutboxEvent.created_at.asc())
            .limit(1)
        )
        first_payload = ob_res.scalars().first()
        if isinstance(first_payload, dict):
            carrier = first_payload.get("trace_context")

    parent_ctx = extract_trace_context(carrier)
    tracer = get_tracer()

    # 3. Start Heartbeat background task
    stop_event = asyncio.Event()
    fenced_event = asyncio.Event()
    heartbeat_task = asyncio.create_task(
        _heartbeat_loop(
            factory,
            run_id,
            epoch,
            lease_secs,
            heartbeat_secs,
            stop_event,
            fenced_event,
        )
    )

    step_count = 0
    run_span = tracer.start_span("worker.execute_run", context=parent_ctx)
    run_span.set_attribute("flowforge.run_id", str(run_id))
    run_span.set_attribute("flowforge.attempt_epoch", epoch)
    span_token = trace.use_span(run_span, end_on_exit=True)
    span_token.__enter__()

    try:
        while current_step_id and not fenced_event.is_set():
            if step_count >= MAX_STEPS_PER_RUN:
                logger.error("Run %s exceeded max step limit (%d)", run_id, MAX_STEPS_PER_RUN)
                break
            step_count += 1

            # Check cancel_requested from DB
            async with factory() as session:
                async with session.begin():
                    chk = await session.execute(
                        select(WorkflowRun.cancel_requested).where(
                            WorkflowRun.id == run_id,
                            WorkflowRun.state == "RUNNING",
                            WorkflowRun.attempt_epoch == epoch,
                        )
                    )
                    is_cancelled = chk.scalar_one_or_none()
                    if is_cancelled:
                        await session.execute(
                            text("""
                                UPDATE workflow_runs
                                SET state = 'CANCELLED',
                                    finished_at = now(),
                                    lease_owner = NULL,
                                    lease_expires_at = NULL,
                                    updated_at = now()
                                WHERE id = :run_id AND state = 'RUNNING' AND attempt_epoch = :epoch
                            """),
                            {"run_id": run_id, "epoch": epoch},
                        )
                        logger.info("Run %s cancelled by user request", run_id)
                        return

            step_def = steps_by_id.get(current_step_id)
            if not step_def:
                logger.error("Step %s not found in definition for run %s", current_step_id, run_id)
                async with factory() as session:
                    async with session.begin():
                        await session.execute(
                            text("""
                                UPDATE workflow_runs
                                SET state = 'FAILED',
                                    error_code = 'STEP_NOT_FOUND',
                                    error_detail = :detail,
                                    finished_at = now(),
                                    lease_owner = NULL,
                                    lease_expires_at = NULL,
                                    updated_at = now()
                                WHERE id = :run_id AND state = 'RUNNING' AND attempt_epoch = :epoch
                            """),
                            {
                                "run_id": run_id,
                                "epoch": epoch,
                                "detail": f"Step '{current_step_id}' not found",
                            },
                        )
                return

            approved_approval_row: ApprovalRequest | None = None
            if step_def.get("type") == "approval":
                async with factory() as session:
                    app_res = await session.execute(
                        select(ApprovalRequest).where(
                            ApprovalRequest.run_id == run_id,
                            ApprovalRequest.step_id == current_step_id,
                            ApprovalRequest.version_id == version_id,
                            ApprovalRequest.state == "APPROVED",
                        )
                    )
                    approved_approval_row = app_res.scalar_one_or_none()

                if not approved_approval_row:
                    scope = build_scope(inputs, context)
                    raw_summary = step_def.get("config", {}).get("summary", "Approval required")
                    rendered_summary = redact(resolve_value(raw_summary, scope))
                    if not isinstance(rendered_summary, dict):
                        rendered_summary = {"summary": str(rendered_summary)}

                    expires_in = int(step_def.get("config", {}).get("expires_in_seconds") or 86400)
                    assigned_role = step_def.get("config", {}).get("assigned_role", "reviewer")

                    async with factory() as session:
                        async with session.begin():
                            f_chk = await session.execute(
                                select(WorkflowRun.id)
                                .where(
                                    WorkflowRun.id == run_id,
                                    WorkflowRun.state == "RUNNING",
                                    WorkflowRun.attempt_epoch == epoch,
                                )
                                .with_for_update()
                            )
                            if not f_chk.scalar_one_or_none():
                                logger.warning("Fenced when checking approval for run %s", run_id)
                                return

                            pend_chk = await session.execute(
                                select(ApprovalRequest.id).where(
                                    ApprovalRequest.run_id == run_id,
                                    ApprovalRequest.step_id == current_step_id,
                                    ApprovalRequest.state == "PENDING",
                                )
                            )
                            if not pend_chk.scalar_one_or_none():
                                new_app = ApprovalRequest(
                                    id=new_id(),
                                    org_id=org_id,
                                    run_id=run_id,
                                    step_id=current_step_id,
                                    version_id=version_id,
                                    assigned_role=assigned_role,
                                    state="PENDING",
                                    summary=rendered_summary,
                                    expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
                                )
                                session.add(new_app)

                            await session.execute(
                                text("""
                                    UPDATE workflow_runs
                                    SET state = 'WAITING_APPROVAL',
                                        lease_owner = NULL,
                                        lease_expires_at = NULL,
                                        current_step_id = :step_id,
                                        updated_at = now()
                                    WHERE id = :run_id
                                      AND state = 'RUNNING'
                                      AND attempt_epoch = :epoch
                                """),
                                {"run_id": run_id, "step_id": current_step_id, "epoch": epoch},
                            )
                            logger.info(
                                "Run %s paused at approval step %s (R4)", run_id, current_step_id
                            )
                            return

            # Check if current_step_id already has SUCCEEDED row
            async with factory() as session:
                succeeded_row = await session.execute(
                    select(StepAttempt.output).where(
                        StepAttempt.run_id == run_id,
                        StepAttempt.step_id == current_step_id,
                        StepAttempt.status == "SUCCEEDED",
                    )
                )
                prev_output = succeeded_row.scalar_one_or_none()

            if prev_output is not None:
                context[current_step_id] = prev_output
                # Advance step according to step type
                step_type = step_def.get("type")
                if step_type == "set_data":
                    current_step_id = step_def.get("next")
                elif step_type == "condition":
                    cond_cfg = ConditionConfig.model_validate(step_def.get("config", {}))
                    current_step_id = evaluate_condition(cond_cfg, inputs, context)
                else:
                    current_step_id = step_def.get("next")
                continue

            # Determine attempt_no
            async with factory() as session:
                max_att_res = await session.execute(
                    select(func.coalesce(func.max(StepAttempt.attempt_no), 0)).where(
                        StepAttempt.run_id == run_id,
                        StepAttempt.step_id == current_step_id,
                    )
                )
                attempt_no = (max_att_res.scalar_one() or 0) + 1

            # Transaction A: Record attempt as RUNNING with epoch guard
            step_attempt_id = new_id()
            step_type = step_def.get("type", "unknown")
            step_input = redact(step_def.get("config", {}))

            async with factory() as session:
                async with session.begin():
                    # Fencing check on workflow_runs
                    fence_chk = await session.execute(
                        select(WorkflowRun.id)
                        .where(
                            WorkflowRun.id == run_id,
                            WorkflowRun.state == "RUNNING",
                            WorkflowRun.attempt_epoch == epoch,
                        )
                        .with_for_update()
                    )
                    if not fence_chk.scalar_one_or_none():
                        logger.warning("Fenced in Transaction A for run %s", run_id)
                        return

                    new_attempt = StepAttempt(
                        id=step_attempt_id,
                        run_id=run_id,
                        org_id=org_id,
                        step_id=current_step_id,
                        step_type=step_type,
                        attempt_no=attempt_no,
                        status="RUNNING",
                        input=step_input,
                        epoch=epoch,
                        started_at=datetime.now(UTC),
                    )
                    session.add(new_attempt)

            # Step Execution outside DB transaction
            start_perf = time.perf_counter()
            step_error_code: str | None = None
            step_error_detail: str | None = None
            step_output: dict[str, Any] = {}
            next_step_id: str | None = None
            step_retryable = False
            step_retry_after: float | None = None
            max_attempts = int(
                step_def.get("config", {}).get("max_attempts")
                or (3 if step_type == "http_request" else 1)
            )

            try:
                with tracer.start_as_current_span(f"worker.step.{step_type}") as step_span:
                    step_span.set_attribute("flowforge.step_id", str(current_step_id))
                    step_span.set_attribute("flowforge.attempt_no", attempt_no)

                    if step_type == "set_data":
                        scope = build_scope(inputs, context)
                        raw_values = step_def.get("config", {}).get("values", {})
                        step_output = resolve_value(raw_values, scope)
                        next_step_id = step_def.get("next")
                    elif step_type == "condition":
                        cond_cfg = ConditionConfig.model_validate(step_def.get("config", {}))
                        next_step_id = evaluate_condition(cond_cfg, inputs, context)
                        step_output = {"selected_branch": next_step_id}
                    elif step_type == "approval":
                        assert approved_approval_row is not None
                        step_output = {
                            "decision": "approved",
                            "decided_by": (
                                str(approved_approval_row.decided_by)
                                if approved_approval_row.decided_by
                                else None
                            ),
                            "decided_at": (
                                approved_approval_row.decided_at.isoformat()
                                if approved_approval_row.decided_at
                                else None
                            ),
                        }
                        next_step_id = step_def.get("next")
                    elif step_type == "http_request":
                        cfg_http = step_def.get("config", {})
                        effect = cfg_http.get("effect") or (
                            "read" if cfg_http.get("method") == "GET" else "write"
                        )
                        cred_id = cfg_http.get("credential_id")
                        is_irreversible = False

                        if effect == "write":
                            if cred_id:
                                async with factory() as session:
                                    cred_res = await session.execute(
                                        select(IntegrationCredential.permission_scopes).where(
                                            IntegrationCredential.id == UUID(str(cred_id)),
                                            IntegrationCredential.org_id == org_id,
                                        )
                                    )
                                    scopes = cred_res.scalar_one_or_none() or []
                                    if "irreversible" in scopes:
                                        is_irreversible = True
                            else:
                                is_irreversible = True

                        if is_irreversible:
                            dom_map = compute_dominators(
                                definition_json.get("start", ""),
                                definition_json.get("steps", []),
                            )
                            strict_doms = dom_map.get(current_step_id, set()) - {current_step_id}

                            async with factory() as session:
                                app_res = await session.execute(
                                    select(ApprovalRequest.step_id).where(
                                        ApprovalRequest.run_id == run_id,
                                        ApprovalRequest.version_id == version_id,
                                        ApprovalRequest.state == "APPROVED",
                                    )
                                )
                                approved_step_ids = set(app_res.scalars().all())

                            if not strict_doms.intersection(approved_step_ids):
                                step_error_code = "FORBIDDEN_TOOL_PERMISSION"
                                step_error_detail = (
                                    "Irreversible operation requires dominating approved approval"
                                    " step"
                                )
                                step_retryable = False

                        if not step_error_code:
                            http_res = await execute_http_step(
                                step_def=step_def,
                                run_id=run_id,
                                org_id=org_id,
                                inputs=inputs,
                                context=context,
                                session_factory=factory,
                                client_override=http_client,
                            )
                            if http_res.success:
                                step_output = http_res.output or {}
                                next_step_id = step_def.get("next")
                            else:
                                step_error_code = http_res.error_code or "STEP_HTTP_ERROR"
                                step_error_detail = http_res.error_detail
                                step_retryable = http_res.retryable
                                step_retry_after = http_res.retry_after
                    elif step_type in ("llm_classify", "llm_transform"):
                        cfg_ai = step_def.get("config", {})
                        max_tokens = int(cfg_ai.get("max_tokens", 1000))
                        async with factory() as session:
                            async with session.begin():
                                try:
                                    await reserve_budget(
                                        session,
                                        org_id=org_id,
                                        run_id=run_id,
                                        step_id=current_step_id,
                                        max_tokens=max_tokens,
                                    )
                                except BudgetExceededError as b_err:
                                    step_error_code = "BUDGET_EXCEEDED"
                                    step_error_detail = str(b_err)
                                    step_retryable = False

                        if not step_error_code:
                            ai_res = await execute_ai_step(
                                step_def=step_def,
                                run_id=run_id,
                                org_id=org_id,
                                attempt_id=step_attempt_id,
                                inputs=inputs,
                                context=context,
                                session_factory=factory,
                                client_override=llm_client,
                                http_client=http_client,
                            )
                            if ai_res.success:
                                step_output = ai_res.output or {}
                                next_step_id = step_def.get("next")
                                async with factory() as session:
                                    async with session.begin():
                                        await settle_budget(
                                            session,
                                            org_id=org_id,
                                            run_id=run_id,
                                            step_id=current_step_id,
                                        )
                            else:
                                step_error_code = ai_res.error_code or "LLM_PROVIDER_ERROR"
                                step_error_detail = ai_res.error_detail
                                step_retryable = ai_res.retryable
                                async with factory() as session:
                                    async with session.begin():
                                        await settle_budget(
                                            session,
                                            org_id=org_id,
                                            run_id=run_id,
                                            step_id=current_step_id,
                                        )
                    else:
                        raise ValueError(f"Unsupported step type: {step_type}")
            except TemplateResolutionError as exc:
                step_error_code = "TEMPLATE_RESOLUTION_ERROR"
                step_error_detail = str(exc)
            except Exception as exc:
                step_error_code = "STEP_EXECUTION_FAILED"
                step_error_detail = str(exc)

            duration_ms = int((time.perf_counter() - start_perf) * 1000)

            # Transaction B: Record step result and advance, retry, or fail
            async with factory() as session:
                async with session.begin():
                    # Fencing check
                    fence_b = await session.execute(
                        select(WorkflowRun)
                        .where(
                            WorkflowRun.id == run_id,
                            WorkflowRun.state == "RUNNING",
                            WorkflowRun.attempt_epoch == epoch,
                        )
                        .with_for_update()
                    )
                    run_row = fence_b.scalar_one_or_none()
                    if not run_row:
                        logger.warning("Fenced in Transaction B for run %s", run_id)
                        return

                    # Update step attempt
                    att_res = await session.execute(
                        select(StepAttempt).where(StepAttempt.id == step_attempt_id)
                    )
                    attempt_row = att_res.scalar_one()
                    attempt_row.ended_at = datetime.now(UTC)
                    attempt_row.duration_ms = duration_ms

                    if step_error_code:
                        attempt_row.status = "FAILED"
                        STEP_ATTEMPTS_TOTAL.labels(step_type=step_type, status="FAILED").inc()
                        attempt_row.error_code = step_error_code
                        attempt_row.error_detail = step_error_detail
                        attempt_row.retryable = step_retryable

                        # Check if retryable and attempt_no < max_attempts
                        if step_retryable and attempt_no < max_attempts:
                            backoff_secs = compute_backoff_seconds(attempt_no, step_retry_after)
                            run_row.state = "QUEUED"
                            run_row.next_attempt_at = datetime.now(UTC) + timedelta(
                                seconds=backoff_secs
                            )
                            run_row.lease_owner = None
                            run_row.lease_expires_at = None
                            run_row.updated_at = datetime.now(UTC)
                            logger.info(
                                "Run %s queued for retry at %s (attempt %d/%d, backoff %.2fs)",
                                run_id,
                                run_row.next_attempt_at,
                                attempt_no,
                                max_attempts,
                                backoff_secs,
                            )
                            return
                        else:
                            run_row.state = "FAILED"
                            RUNS_TOTAL.labels(state="FAILED").inc()
                            if step_retryable and attempt_no >= max_attempts:
                                run_row.error_code = "STEP_RETRIES_EXHAUSTED"
                            else:
                                run_row.error_code = step_error_code
                            run_row.error_detail = step_error_detail
                            run_row.finished_at = datetime.now(UTC)
                            run_row.lease_owner = None
                            run_row.lease_expires_at = None
                            run_row.updated_at = datetime.now(UTC)
                            logger.info(
                                "Run %s failed at step %s: %s (code=%s)",
                                run_id,
                                current_step_id,
                                step_error_detail,
                                run_row.error_code,
                            )
                            return
                    else:
                        attempt_row.status = "SUCCEEDED"
                        STEP_ATTEMPTS_TOTAL.labels(step_type=step_type, status="SUCCEEDED").inc()
                        attempt_row.output = redact(step_output)

                        # Check cancel_requested before advancing or completing
                        if run_row.cancel_requested:
                            run_row.state = "CANCELLED"
                            RUNS_TOTAL.labels(state="CANCELLED").inc()
                            run_row.finished_at = datetime.now(UTC)
                            run_row.lease_owner = None
                            run_row.lease_expires_at = None
                            run_row.updated_at = datetime.now(UTC)
                            logger.info("Run %s cancelled at step boundary", run_id)
                            return

                        # Update run context and step pointer
                        context[current_step_id] = step_output
                        run_row.context = context
                        run_row.current_step_id = next_step_id
                        run_row.updated_at = datetime.now(UTC)

                        if next_step_id is None:
                            # Workflow completed successfully (R6)
                            run_row.state = "SUCCEEDED"
                            RUNS_TOTAL.labels(state="SUCCEEDED").inc()
                            run_row.outputs = redact(step_output)
                            run_row.finished_at = datetime.now(UTC)
                            run_row.lease_owner = None
                            run_row.lease_expires_at = None
                            logger.info("Run %s succeeded successfully", run_id)

            current_step_id = next_step_id

    finally:
        span_token.__exit__(None, None, None)
        stop_event.set()
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
