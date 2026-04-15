from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import SyncJobPayload, SyncJobResponse, SyncOverview
from app.services.sync import get_provider_statuses, get_sync_job, list_sync_jobs, queue_sync_job, retry_sync_job, serialize_sync_job

router = APIRouter()


@router.get("/", response_model=SyncOverview)
async def sync_overview(db: AsyncSession = Depends(get_db)) -> SyncOverview:
    return SyncOverview(providers=await get_provider_statuses(), jobs=await list_sync_jobs(db, limit=25))


@router.get("/jobs", response_model=list[SyncJobResponse])
async def sync_jobs(
    db: AsyncSession = Depends(get_db),
    status_filter: str | None = Query(default=None, alias="status"),
    job_type: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=200),
) -> list[SyncJobResponse]:
    return await list_sync_jobs(db, limit=limit, status=status_filter, job_type=job_type)


@router.get("/jobs/{job_id}", response_model=SyncJobResponse)
async def sync_job_detail(job_id: int, db: AsyncSession = Depends(get_db)) -> SyncJobResponse:
    job = await get_sync_job(db, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.post("/jobs", response_model=SyncJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_sync(payload: SyncJobPayload) -> SyncJobResponse:
    job = await queue_sync_job(payload.job_type, force=payload.force, payload=payload.payload)
    return serialize_sync_job(job)


@router.post("/jobs/{job_id}/retry", response_model=SyncJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def retry_failed_job(job_id: int) -> SyncJobResponse:
    try:
        job = await retry_sync_job(job_id)
        return serialize_sync_job(job)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
