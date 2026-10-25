"""Integration tests for the Transactional Outbox Publisher (P4-T07, P4-T08)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.ids import new_id
from app.infrastructure.messaging.outbox_publisher import publish_batch
from app.modules.executions.models import OutboxEvent


@pytest.mark.asyncio
async def test_publish_batch_success_and_concurrency(db_engine: AsyncEngine) -> None:
    """P4-T07: publish_batch publishes unpublished events and SKIP LOCKED prevents duplicate dispatch."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    # Insert 10 unpublished outbox events
    async with factory() as session:
        async with session.begin():
            for i in range(10):
                event = OutboxEvent(
                    id=new_id(),
                    aggregate_type="run",
                    aggregate_id=uuid4(),
                    event_type="RunRequested",
                    payload={"idx": i},
                )
                session.add(event)

    published_events: list[str] = []

    async def mock_broker(event: OutboxEvent) -> None:
        published_events.append(str(event.id))
        await asyncio.sleep(0.01)

    # Run two concurrent publish_batch tasks
    task1 = asyncio.create_task(publish_batch(factory, broker_publish=mock_broker, batch_size=5))
    task2 = asyncio.create_task(publish_batch(factory, broker_publish=mock_broker, batch_size=5))
    count1, count2 = await asyncio.gather(task1, task2)

    assert count1 + count2 == 10
    # Crucial property: No duplicate dispatch across concurrent workers
    assert len(published_events) == 10
    assert len(set(published_events)) == 10

    # Verify all 10 are marked published
    async with factory() as session:
        res = await session.execute(
            select(OutboxEvent).where(OutboxEvent.published_at.is_not(None))
        )
        assert len(res.scalars().all()) == 10


@pytest.mark.asyncio
async def test_publish_batch_broker_failure_backoff(db_engine: AsyncEngine) -> None:
    """P4-T08: Broker failure increments publish_attempts and sets exponential next_publish_at."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    event_id = new_id()

    async with factory() as session:
        async with session.begin():
            event = OutboxEvent(
                id=event_id,
                aggregate_type="run",
                aggregate_id=uuid4(),
                event_type="RunRequested",
                payload={"fail": True},
            )
            session.add(event)

    def failing_broker(event: OutboxEvent) -> None:
        raise ConnectionError("RabbitMQ broker unreachable")

    # Run publish_batch with failing broker
    count = await publish_batch(factory, broker_publish=failing_broker)
    assert count == 0

    async with factory() as session:
        ev = await session.get(OutboxEvent, event_id)
        assert ev is not None
        assert ev.published_at is None
        assert ev.publish_attempts == 1
        assert ev.next_publish_at > datetime.now(UTC)
