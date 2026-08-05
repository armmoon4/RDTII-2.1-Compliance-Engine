"""Celery application instance."""
from celery import Celery
from app.config import settings

celery_app = Celery(
    "rdtii_worker",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=86400,  # 24 hours
)

# Force solo pool (single-process, no fork) to avoid OOM from ForkPool
# memory duplication when loading ML models (sentence-transformers, spaCy).
# The CLI --pool=solo in docker-compose.yml may not take effect on
# pre-existing containers; this ensures it's always set.
celery_app.conf.worker_pool = "solo"
