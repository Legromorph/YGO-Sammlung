from __future__ import annotations

import asyncio

from app.celery_app import celery_app


@celery_app.task(name="app.worker.run_sync_job")
def run_sync_job(job_id: int) -> None:
    from app.services.sync import execute_sync_job

    asyncio.run(execute_sync_job(job_id))


@celery_app.task(name="app.worker.enqueue_price_sync")
def enqueue_price_sync() -> None:
    from app.services.sync import queue_sync_job

    asyncio.run(queue_sync_job("price_update", payload={"trigger": "scheduler"}))


@celery_app.task(name="app.worker.enqueue_image_sync")
def enqueue_image_sync() -> None:
    from app.services.sync import queue_sync_job

    asyncio.run(queue_sync_job("image_sync", payload={"trigger": "scheduler"}))


@celery_app.task(name="app.worker.enqueue_trend_rebuild")
def enqueue_trend_rebuild() -> None:
    from app.services.sync import queue_sync_job

    asyncio.run(queue_sync_job("trend_rebuild", payload={"trigger": "scheduler"}))


@celery_app.task(name="app.worker.enqueue_card_data_sync")
def enqueue_card_data_sync() -> None:
    from app.services.sync import queue_sync_job

    asyncio.run(queue_sync_job("card_data_sync", payload={"trigger": "scheduler"}))
