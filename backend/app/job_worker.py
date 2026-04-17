from __future__ import annotations

import asyncio
import logging
import os
import socket

from app.config import settings
from app.services.sync import claim_next_sync_job, fail_stale_running_jobs, process_claimed_sync_job


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def _worker_name() -> str:
    explicit_name = os.getenv("SYNC_WORKER_NAME")
    if explicit_name:
        return explicit_name
    return f"{socket.gethostname()}:{os.getpid()}"


async def run_worker() -> None:
    worker_name = _worker_name()
    max_parallel_jobs = max(1, settings.sync_worker_max_parallel_jobs)
    logger.info("Starting sync worker %s", worker_name)
    active_tasks: set[asyncio.Task[None]] = set()

    async def run_claimed_job(job_id: int) -> None:
        try:
            await process_claimed_sync_job(job_id, worker_name=worker_name)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unexpected error while processing claimed job %s", job_id)

    while True:
        try:
            await fail_stale_running_jobs()

            claimed_any = False
            while len(active_tasks) < max_parallel_jobs:
                job = await claim_next_sync_job(worker_name=worker_name)
                if not job:
                    break
                claimed_any = True
                task = asyncio.create_task(run_claimed_job(job.id), name=f"sync-job-{job.id}")
                active_tasks.add(task)
                task.add_done_callback(active_tasks.discard)

            if active_tasks:
                await asyncio.wait(
                    active_tasks,
                    timeout=0 if claimed_any else settings.sync_worker_poll_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                continue

            await asyncio.sleep(settings.sync_worker_poll_seconds)
        except asyncio.CancelledError:
            if active_tasks:
                await asyncio.gather(*active_tasks, return_exceptions=True)
            raise
        except Exception:
            logger.exception("Unexpected error in sync worker loop")
            await asyncio.sleep(max(2, settings.sync_worker_poll_seconds))


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
