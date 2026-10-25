"""Celery application configuration."""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "flowforge",
    broker=settings.rabbitmq_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_default_queue=settings.celery_task_queue,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)
