"""Celery application configured against the shared Redis service."""

from celery import Celery

from backend.app.core.config import settings

celery_app = Celery(
    "ecochain",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["backend.app.workers.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
)
