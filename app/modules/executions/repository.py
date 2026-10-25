"""Database repository for workflow runs, step attempts, and outbox events."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, func, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.core.pagination import decode_cursor, encode_cursor
from app.modules.executions.models import OutboxEvent, StepAttempt, WorkflowRun
from app.modules.organizations.models import Membership, Organization
from app.modules.workflows.models import WorkflowVersion


class ExecutionRepository:
    """Encapsulates tenant-isolated database access for workflow executions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id_for_user(
        self,
        run_id: UUID,
        *,
        user_id: UUID,
    ) -> tuple[WorkflowRun, int, str] | None:
        """Retrieve a run joined with user membership in the run's organization."""
        stmt = (
            select(WorkflowRun, WorkflowVersion.version, Membership.role)
            .join(WorkflowVersion, WorkflowRun.version_id == WorkflowVersion.id)
            .join(
                Membership,
                and_(
                    Membership.org_id == WorkflowRun.org_id,
                    Membership.user_id == user_id,
                ),
            )
            .where(WorkflowRun.id == run_id)
        )
        result = await self.session.execute(stmt)
        row = result.first()
        if not row:
            return None
        return row[0], row[1], row[2]

    async def get_run_by_id(
        self,
        run_id: UUID,
        *,
        org_id: UUID,
    ) -> tuple[WorkflowRun, int] | None:
        """Retrieve a run with its workflow version number strictly scoped to org_id."""
        stmt = (
            select(WorkflowRun, WorkflowVersion.version)
            .join(WorkflowVersion, WorkflowRun.version_id == WorkflowVersion.id)
            .where(
                and_(
                    WorkflowRun.id == run_id,
                    WorkflowRun.org_id == org_id,
                )
            )
        )
        result = await self.session.execute(stmt)
        row = result.first()
        if not row:
            return None
        return row[0], row[1]

    async def get_run_by_idempotency_key(
        self,
        idempotency_key: str,
        *,
        org_id: UUID,
    ) -> tuple[WorkflowRun, int] | None:
        """Find an existing run by idempotency key within tenant org."""
        stmt = (
            select(WorkflowRun, WorkflowVersion.version)
            .join(WorkflowVersion, WorkflowRun.version_id == WorkflowVersion.id)
            .where(
                and_(
                    WorkflowRun.org_id == org_id,
                    WorkflowRun.idempotency_key == idempotency_key,
                )
            )
        )
        result = await self.session.execute(stmt)
        row = result.first()
        if not row:
            return None
        return row[0], row[1]

    async def lock_organization_for_concurrency(
        self,
        *,
        org_id: UUID,
    ) -> int | None:
        """Acquire exclusive row-level lock on organization and return max_concurrent_runs."""
        stmt = (
            select(Organization.max_concurrent_runs)
            .where(Organization.id == org_id)
            .with_for_update()
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_active_runs(
        self,
        *,
        org_id: UUID,
    ) -> int:
        """Count active (QUEUED or RUNNING) workflow runs for an organization."""
        stmt = (
            select(func.count())
            .select_from(WorkflowRun)
            .where(
                and_(
                    WorkflowRun.org_id == org_id,
                    WorkflowRun.state.in_(["QUEUED", "RUNNING"]),
                )
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one() or 0

    async def create_run_and_outbox(
        self,
        run: WorkflowRun,
        outbox: OutboxEvent,
        *,
        org_id: UUID,
    ) -> WorkflowRun:
        """Persist a newly queued run and its outbox event atomically."""
        assert run.org_id == org_id
        self.session.add(run)
        self.session.add(outbox)
        await self.session.flush()
        return run

    async def list_runs_by_org(
        self,
        *,
        org_id: UUID,
        limit: int = 50,
        cursor: str | None = None,
        state: str | None = None,
        workflow_id: UUID | None = None,
    ) -> tuple[list[tuple[WorkflowRun, int]], str | None]:
        """List workflow runs for an organization with cursor pagination."""
        stmt = (
            select(WorkflowRun, WorkflowVersion.version)
            .join(WorkflowVersion, WorkflowRun.version_id == WorkflowVersion.id)
            .where(WorkflowRun.org_id == org_id)
        )

        if state:
            stmt = stmt.where(WorkflowRun.state == state)
        if workflow_id:
            stmt = stmt.where(WorkflowRun.workflow_id == workflow_id)

        if cursor:
            payload = decode_cursor(cursor)
            stmt = stmt.where(
                tuple_(WorkflowRun.created_at, WorkflowRun.id) < (payload.created_at, payload.id)
            )

        stmt = stmt.order_by(WorkflowRun.created_at.desc(), WorkflowRun.id.desc()).limit(limit + 1)

        result = await self.session.execute(stmt)
        rows: Sequence[tuple[WorkflowRun, int]] = result.all()

        has_next = len(rows) > limit
        selected_rows = list(rows[:limit])

        next_cursor: str | None = None
        if has_next and selected_rows:
            last_run = selected_rows[-1][0]
            next_cursor = encode_cursor(last_run.created_at, last_run.id)

        return selected_rows, next_cursor

    async def list_step_attempts(
        self,
        run_id: UUID,
        *,
        org_id: UUID,
    ) -> list[StepAttempt]:
        """List step attempts for a run ordered by started_at ASC, attempt_no ASC."""
        stmt = (
            select(StepAttempt)
            .where(
                and_(
                    StepAttempt.run_id == run_id,
                    StepAttempt.org_id == org_id,
                )
            )
            .order_by(StepAttempt.started_at.asc(), StepAttempt.attempt_no.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def cancel_run(
        self,
        run_id: UUID,
        *,
        org_id: UUID,
    ) -> tuple[WorkflowRun, int] | None:
        """Cancel a run in QUEUED/WAITING_APPROVAL (R9) or flag on RUNNING (R10)."""
        # Try R9 on QUEUED or WAITING_APPROVAL
        r9_stmt = text("""
            UPDATE workflow_runs
            SET state = 'CANCELLED',
                cancel_requested = true,
                finished_at = now(),
                updated_at = now()
            WHERE id = :run_id AND org_id = :org_id AND state IN ('QUEUED', 'WAITING_APPROVAL')
        """)
        res = await self.session.execute(r9_stmt, {"run_id": run_id, "org_id": org_id})
        if getattr(res, "rowcount", 0) > 0:
            # Also cancel any pending approvals for this run
            await self.session.execute(
                text("""
                    UPDATE approval_requests
                    SET state = 'CANCELLED'
                    WHERE run_id = :run_id AND org_id = :org_id AND state = 'PENDING'
                """),
                {"run_id": run_id, "org_id": org_id},
            )
            found = await self.get_run_by_id(run_id, org_id=org_id)
            if found:
                await self.session.refresh(found[0])
            return found

        # Try setting cancel_requested on RUNNING
        r10_flag_stmt = text("""
            UPDATE workflow_runs
            SET cancel_requested = true,
                updated_at = now()
            WHERE id = :run_id AND org_id = :org_id AND state = 'RUNNING'
        """)
        res = await self.session.execute(r10_flag_stmt, {"run_id": run_id, "org_id": org_id})
        if getattr(res, "rowcount", 0) > 0:
            found = await self.get_run_by_id(run_id, org_id=org_id)
            if found:
                await self.session.refresh(found[0])
            return found

        return None

    async def retry_run(
        self,
        run_id: UUID,
        *,
        org_id: UUID,
    ) -> tuple[WorkflowRun, int] | None:
        """Retry a failed workflow run (R11) and enqueue RunRequested outbox event."""
        # Execute R11
        r11_stmt = text("""
            UPDATE workflow_runs
            SET state = 'QUEUED',
                error_code = NULL,
                error_detail = NULL,
                finished_at = NULL,
                next_attempt_at = now(),
                updated_at = now()
            WHERE id = :run_id AND org_id = :org_id AND state = 'FAILED'
        """)
        res = await self.session.execute(r11_stmt, {"run_id": run_id, "org_id": org_id})
        if getattr(res, "rowcount", 0) == 0:
            return None

        # Insert outbox event in the same transaction
        event = OutboxEvent(
            id=new_id(),
            aggregate_type="run",
            aggregate_id=run_id,
            event_type="RunRequested",
            schema_version=1,
            payload={
                "run_id": str(run_id),
                "org_id": str(org_id),
                "reason": "manual_retry",
            },
            next_publish_at=datetime.now(UTC),
        )
        self.session.add(event)
        await self.session.flush()

        found = await self.get_run_by_id(run_id, org_id=org_id)
        if found:
            await self.session.refresh(found[0])
        return found
