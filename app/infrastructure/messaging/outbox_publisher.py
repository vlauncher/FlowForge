"""Transactional outbox publisher loop for dispatching events to RabbitMQ/Celery."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.modules.executions.models import OutboxEvent
from app.observability.tracing import extract_trace_context, get_tracer

logger = logging.getLogger("flowforge.messaging.outbox")


async def publish_batch(
    session_factory: async_sessionmaker[AsyncSession],
    broker_publish: Callable[[OutboxEvent], Any] | None = None,
    batch_size: int = 100,
) -> int:
    """Publish a batch of unpublished outbox events using SKIP LOCKED row-level concurrency."""
    settings = get_settings()
    published_count = 0

    async with session_factory() as session:
        async with session.begin():
            now = datetime.now(UTC)
            stmt = (
                select(OutboxEvent)
                .where(
                    OutboxEvent.published_at.is_(None),
                    OutboxEvent.next_publish_at <= now,
                )
                .order_by(OutboxEvent.created_at.asc(), OutboxEvent.id.asc())
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )

            result = await session.execute(stmt)
            events = list(result.scalars().all())

            if not events:
                return 0

            for event in events:
                try:
                    carrier = (
                        event.payload.get("trace_context")
                        if isinstance(event.payload, dict)
                        else None
                    )
                    parent_ctx = extract_trace_context(carrier)
                    tracer = get_tracer()
                    with tracer.start_as_current_span("outbox.publish", context=parent_ctx) as span:
                        span.set_attribute("flowforge.event_id", str(event.id))
                        span.set_attribute("flowforge.aggregate_id", str(event.aggregate_id))

                        if broker_publish is not None:
                            res = broker_publish(event)
                            if inspect.isawaitable(res):
                                await res
                        else:
                            # Default Celery publish
                            from app.workers.celery_app import celery_app

                            celery_app.send_task(
                                "runs.execute_run",
                                args=[str(event.aggregate_id)],
                                task_id=str(event.id),
                                queue=settings.celery_task_queue,
                            )

                    event.published_at = datetime.now(UTC)
                    published_count += 1
                except Exception as exc:
                    logger.warning(
                        "Failed to publish outbox event %s (attempt %d): %s",
                        event.id,
                        event.publish_attempts + 1,
                        exc,
                    )
                    event.publish_attempts += 1
                    backoff_secs = min(60, 2**event.publish_attempts)
                    event.next_publish_at = datetime.now(UTC) + timedelta(seconds=backoff_secs)

    return published_count
