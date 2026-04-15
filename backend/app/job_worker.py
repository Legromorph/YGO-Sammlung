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
    logger.info("Starting sync worker %s", worker_name)

    while True:
        try:
            await fail_stale_running_jobs()
            job = await claim_next_sync_job(worker_name=worker_name)
            if not job:
                await asyncio.sleep(settings.sync_worker_poll_seconds)
                continue
            await process_claimed_sync_job(job.id, worker_name=worker_name)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unexpected error in sync worker loop")
            await asyncio.sleep(max(2, settings.sync_worker_poll_seconds))


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
