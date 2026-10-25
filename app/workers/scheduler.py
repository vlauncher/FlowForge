"""Background scheduler process for outbox publishing and lease maintenance."""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from typing import Any

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.infrastructure.db.session import get_session_factory
from app.infrastructure.messaging.outbox_publisher import publish_batch
from app.infrastructure.messaging.topology import declare_topology
from app.workers.sweeper import sweep_stale_and_delayed_runs

logger = logging.getLogger("flowforge.workers.scheduler")


async def run_scheduler_loop() -> None:
    """Continuously poll outbox and publish pending events to RabbitMQ."""
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("Starting FlowForge scheduler service...")

    # Declare RabbitMQ topology on startup
    try:
        declare_topology()
    except Exception as exc:
        logger.warning("Could not declare RabbitMQ topology on scheduler startup: %s", exc)

    factory = get_session_factory()
    interval = 1.0  # Poll every 1 second
    last_sweep_at = 0.0

    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _on_signal(*_: Any) -> None:
        logger.info("Scheduler received termination signal. Shutting down...")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except NotImplementedError:
            pass

    while not shutdown_event.is_set():
        try:
            published = await publish_batch(factory)
            if published > 0:
                logger.info("Published %d outbox event(s)", published)
        except Exception as exc:
            logger.error("Error in scheduler outbox publisher loop: %s", exc)

        now_ts = time.time()
        if now_ts - last_sweep_at >= settings.sweeper_interval_seconds:
            try:
                recovered = await sweep_stale_and_delayed_runs(factory)
                if recovered > 0:
                    logger.info("Sweeper recovered %d run(s)", recovered)
                last_sweep_at = now_ts
            except Exception as exc:
                logger.error("Error in sweeper recovery loop: %s", exc)

        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
        except TimeoutError:
            pass

    logger.info("Scheduler service stopped cleanly.")


def main() -> None:
    asyncio.run(run_scheduler_loop())


if __name__ == "__main__":
    main()
