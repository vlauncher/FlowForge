"""Recovery sweeper for stale worker leases, delayed retries, and expired approvals."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.ids import new_id
from app.modules.audit.repository import AuditRepository
from app.modules.executions.models import OutboxEvent

logger = logging.getLogger("flowforge.workers.sweeper")


async def sweep_stale_and_delayed_runs(
    session_factory: async_sessionmaker[AsyncSession],
    batch_size: int = 100,
) -> int:
    """Find stale RUNNING leases or mature QUEUED retries and enqueue RunResumeRequested events."""
    recovered_count = 0
    now = datetime.now(UTC)

    async with session_factory() as session:
        async with session.begin():
            stmt = text("""
                SELECT wr.id, wr.org_id, wr.state
                FROM workflow_runs wr
                WHERE (
                    (wr.state = 'RUNNING' AND wr.lease_expires_at < now())
                    OR (
                        wr.state = 'QUEUED'
                        AND (wr.next_attempt_at IS NULL OR wr.next_attempt_at <= now())
                        AND NOT EXISTS (
                            SELECT 1 FROM outbox_events oe
                            WHERE oe.aggregate_id = wr.id AND oe.published_at IS NULL
                        )
                    )
                )
                ORDER BY wr.updated_at ASC
                LIMIT :batch_size
                FOR UPDATE OF wr SKIP LOCKED
            """)

            res = await session.execute(stmt, {"batch_size": batch_size})
            runs = res.mappings().all()

            for r in runs:
                run_id = r["id"]
                org_id = r["org_id"]
                state = r["state"]

                event = OutboxEvent(
                    id=new_id(),
                    aggregate_type="run",
                    aggregate_id=run_id,
                    event_type="RunResumeRequested",
                    schema_version=1,
                    payload={
                        "run_id": str(run_id),
                        "org_id": str(org_id),
                        "reason": f"sweeper_recovery_{state.lower()}",
                    },
                    next_publish_at=now,
                )
                session.add(event)
                recovered_count += 1
                logger.info("Sweeper scheduled recovery for run %s (state: %s)", run_id, state)

    return recovered_count


async def sweep_expired_approvals(
    session_factory: async_sessionmaker[AsyncSession],
    batch_size: int = 100,
) -> int:
    """Find expired PENDING approvals, mark them EXPIRED, fail their runs, and
    record audit event.
    """
    expired_count = 0

    async with session_factory() as session:
        async with session.begin():
            stmt = text("""
                SELECT ar.id, ar.org_id, ar.run_id, ar.step_id
                FROM approval_requests ar
                WHERE ar.state = 'PENDING' AND ar.expires_at <= now()
                ORDER BY ar.expires_at ASC
                LIMIT :batch_size
                FOR UPDATE SKIP LOCKED
            """)
            res = await session.execute(stmt, {"batch_size": batch_size})
            expired_rows = res.mappings().all()

            audit_repo = AuditRepository(session)

            for row in expired_rows:
                app_id = row["id"]
                org_id = row["org_id"]
                run_id = row["run_id"]
                step_id = row["step_id"]

                await session.execute(
                    text("""
                        UPDATE approval_requests
                        SET state = 'EXPIRED'
                        WHERE id = :app_id
                    """),
                    {"app_id": app_id},
                )

                await session.execute(
                    text("""
                        UPDATE workflow_runs
                        SET state = 'FAILED',
                            error_code = 'APPROVAL_EXPIRED',
                            error_detail = 'Approval request expired before decision',
                            finished_at = now(),
                            updated_at = now()
                        WHERE id = :run_id AND state = 'WAITING_APPROVAL'
                    """),
                    {"run_id": run_id},
                )

                await audit_repo.record_audit_event(
                    org_id=org_id,
                    actor_user_id=None,
                    actor_type="system",
                    action="approval.expired",
                    target_type="approval_request",
                    target_id=app_id,
                    metadata={"run_id": str(run_id), "step_id": step_id},
                )
                expired_count += 1
                logger.info("Sweeper expired approval %s for run %s", app_id, run_id)

    return expired_count
