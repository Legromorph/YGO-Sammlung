from __future__ import annotations

from datetime import datetime
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.schemas import BulkSetImportPayload, BulkSetImportResponse
from app.services.inventory import bulk_add_inventory_from_set
from app.services.sync import queue_price_update_job, queue_sync_job, serialize_sync_job

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/bulk-add-from-set", response_model=BulkSetImportResponse, status_code=status.HTTP_201_CREATED)
async def bulk_add_from_set(
    payload: BulkSetImportPayload,
    db: AsyncSession = Depends(get_db),
) -> BulkSetImportResponse:
    try:
        response = await bulk_add_inventory_from_set(db, payload)
        await db.commit()
        price_sync_job = None
        price_sync_job_error = None
        try:
            if response.imported_inventory_item_ids or response.imported_card_print_ids:
                logger.info(
                    "Bulk import batch %s created %s inventory item(s) and %s card print target(s); queueing price job",
                    response.purchase_batch_id,
                    len(response.imported_inventory_item_ids),
                    len(response.imported_card_print_ids),
                )
                price_sync_job = await queue_price_update_job(
                    inventory_item_ids=response.imported_inventory_item_ids,
                    card_print_ids=response.imported_card_print_ids,
                    trigger="bulk_import",
                    reason=f"purchase_batch:{response.purchase_batch_id}",
                    available_at=datetime.utcnow(),
                    priority=settings.price_monitor_new_priority,
                )
                logger.info(
                    "Created price_update job %s for %s imported inventory item(s)",
                    price_sync_job.id,
                    len(response.imported_inventory_item_ids),
                )
        except Exception as exc:  # pragma: no cover - defensive fallback around broker/db availability
            price_sync_job_error = str(exc)
            logger.exception("Failed to queue post-import price job for purchase batch %s", response.purchase_batch_id)
        try:
            if response.imported_card_print_ids:
                await queue_sync_job(
                    "image_sync",
                    payload={
                        "card_print_ids": response.imported_card_print_ids,
                        "trigger": "bulk_import",
                        "reason": f"purchase_batch:{response.purchase_batch_id}",
                    },
                    available_at=datetime.utcnow(),
                )
        except Exception as exc:  # pragma: no cover - defensive fallback around broker/db availability
            logger.exception("Failed to queue post-import image sync for purchase batch %s: %s", response.purchase_batch_id, exc)

        if not price_sync_job and not price_sync_job_error:
            return response

        return response.model_copy(
            update={
                "price_sync_job": (
                    serialize_sync_job(price_sync_job).model_dump()
                    if price_sync_job
                    else None
                ),
                "price_sync_job_error": price_sync_job_error,
            }
        )
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
