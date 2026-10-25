"""Celery task declarations for asynchronous run execution."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from celery import Task

from app.workers.celery_app import celery_app
from app.workers.runner import execute_run

logger = logging.getLogger("flowforge.workers.tasks")


@celery_app.task(  # type: ignore[untyped-decorator]
    name="runs.execute_run",
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=3,
)
def execute_run_task(self: Task, run_id_str: str) -> None:
    """Execute a workflow run to completion or wait state."""
    logger.info("Starting execution of run %s (task_id: %s)", run_id_str, self.request.id)
    run_id = UUID(run_id_str)
    try:
        asyncio.run(execute_run(run_id))
    except Exception as exc:
        logger.exception("Unexpected error executing run %s: %s", run_id_str, exc)
        raise
