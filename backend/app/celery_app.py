from __future__ import annotations

from datetime import timedelta

from celery import Celery

from app.config import settings


celery_app = Celery("ygo_collection", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Europe/Berlin",
    enable_utc=True,
    beat_schedule={
        "enqueue-price-sync": {
            "task": "app.worker.enqueue_price_sync",
            "schedule": timedelta(minutes=settings.price_sync_interval_minutes),
        },
        "enqueue-image-sync": {
            "task": "app.worker.enqueue_image_sync",
            "schedule": timedelta(minutes=settings.image_sync_interval_minutes),
        },
        "enqueue-trend-rebuild": {
            "task": "app.worker.enqueue_trend_rebuild",
            "schedule": timedelta(minutes=settings.trend_sync_interval_minutes),
        },
        "enqueue-card-data-sync": {
            "task": "app.worker.enqueue_card_data_sync",
            "schedule": timedelta(minutes=settings.card_data_sync_interval_minutes),
        },
    },
)
