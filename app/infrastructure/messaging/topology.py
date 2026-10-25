"""RabbitMQ topology declaration using Kombu."""

from __future__ import annotations

import logging

import kombu

from app.core.config import get_settings

logger = logging.getLogger("flowforge.messaging.topology")


def declare_topology(rabbitmq_url: str | None = None) -> None:
    """Declare exchanges and queues for durable workflow execution."""
    settings = get_settings()
    url = rabbitmq_url or settings.rabbitmq_url

    runs_exchange = kombu.Exchange("flowforge.runs", type="direct", durable=True)
    dlx_exchange = kombu.Exchange("flowforge.dlx", type="fanout", durable=True)

    dead_queue = kombu.Queue("runs.dead", exchange=dlx_exchange, durable=True)
    execute_queue = kombu.Queue(
        settings.celery_task_queue,
        exchange=runs_exchange,
        routing_key="run.execute",
        durable=True,
        queue_arguments={
            "x-dead-letter-exchange": "flowforge.dlx",
        },
    )

    try:
        with kombu.Connection(url) as conn:
            conn.connect()
            with conn.channel() as channel:
                runs_exchange(channel).declare()
                dlx_exchange(channel).declare()
                dead_queue(channel).declare()
                execute_queue(channel).declare()
        logger.info("RabbitMQ topology declared successfully.")
    except Exception as exc:
        logger.warning("Could not declare RabbitMQ topology (broker may be unreachable): %s", exc)
        raise
