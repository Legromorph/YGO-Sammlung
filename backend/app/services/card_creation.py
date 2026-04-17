from __future__ import annotations

from datetime import datetime
import logging

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models import CardPrint, InventoryItem, SourceMapping
from app.schemas import CardPayload, CardSummary
from app.services.app_settings import get_app_settings
from app.services.cards import get_card_detail, serialize_card_summary, upsert_card
from app.services.sync import queue_price_update_job, queue_sync_job


logger = logging.getLogger(__name__)

_CARD_SUMMARY_EXCLUDE_FIELDS = {
    "effect_text",
    "subtype",
    "archetype",
    "spell_trap_type",
    "rarity_code",
    "edition",
    "release_date",
    "cardmarket_reference",
    "tags",
    "link_arrows",
    "pendulum_scale",
    "pendulum_effect",
    "price_history",
    "source_mappings",
}


class CardCreationOrchestrator:
    async def create_card(self, db: AsyncSession, payload: CardPayload) -> CardSummary:
        logger.info("Card creation started for '%s' (%s)", payload.name, payload.set_code)
        item = await upsert_card(db, payload)
        await db.commit()
        logger.info("Card creation committed for inventory item %s", item.id)

        await self._queue_follow_up_jobs(item)
        summary = await self._load_created_summary(db, item.id)
        logger.info("Card creation completed successfully for inventory item %s", item.id)
        return summary

    async def _queue_follow_up_jobs(self, item: InventoryItem) -> None:
        try:
            await queue_price_update_job(
                inventory_item_ids=[item.id],
                card_print_ids=[item.card_print_id],
                trigger="create_card",
                reason="new_card_created",
                available_at=datetime.utcnow(),
                priority=settings.price_monitor_new_priority,
            )
        except Exception as exc:  # pragma: no cover - defensive post-create trigger
            logger.exception("Failed to queue initial price update for inventory item %s: %s", item.id, exc)

        try:
            await queue_sync_job(
                "image_sync",
                payload={
                    "card_print_ids": [item.card_print_id],
                    "trigger": "create_card",
                    "reason": "new_card_created",
                },
                available_at=datetime.utcnow(),
            )
        except Exception as exc:  # pragma: no cover - defensive post-create trigger
            logger.exception("Failed to queue initial image sync for card print %s: %s", item.card_print_id, exc)

    async def _load_created_summary(self, db: AsyncSession, inventory_item_id: int) -> CardSummary:
        try:
            detail = await get_card_detail(db, inventory_item_id)
            if detail:
                return CardSummary(**detail.model_dump(exclude=_CARD_SUMMARY_EXCLUDE_FIELDS))
        except Exception as exc:
            logger.exception("Failed after pricing during card creation while loading detail for inventory item %s: %s", inventory_item_id, exc)

        fallback_summary = await self._load_created_summary_fallback(db, inventory_item_id)
        if fallback_summary:
            logger.warning("Card detail reload failed after creation; returning fallback summary for inventory item %s", inventory_item_id)
            return fallback_summary

        raise RuntimeError("Card could not be reloaded after creation")

    async def _load_created_summary_fallback(self, db: AsyncSession, inventory_item_id: int) -> CardSummary | None:
        app_settings = await get_app_settings(db)
        display_currency = app_settings.preferred_currency
        result = await db.execute(
            select(InventoryItem)
            .where(InventoryItem.id == inventory_item_id)
            .options(
                selectinload(InventoryItem.storage_location),
                selectinload(InventoryItem.price_history),
                selectinload(InventoryItem.price_monitor_state),
                selectinload(InventoryItem.card_print).selectinload(CardPrint.card),
                selectinload(InventoryItem.card_print).selectinload(CardPrint.image_assets),
            )
        )
        item = result.scalar_one_or_none()
        if not item:
            return None

        mappings_result = await db.execute(
            select(SourceMapping).where(
                or_(
                    and_(SourceMapping.target_type == "card", SourceMapping.target_id == item.card_print.card.id),
                    and_(SourceMapping.target_type == "card_print", SourceMapping.target_id == item.card_print.id),
                )
            )
        )
        mappings = mappings_result.scalars().all()
        return await serialize_card_summary(item, mappings=mappings, display_currency=display_currency)


_DEFAULT_CARD_CREATION_ORCHESTRATOR = CardCreationOrchestrator()


def get_card_creation_orchestrator() -> CardCreationOrchestrator:
    return _DEFAULT_CARD_CREATION_ORCHESTRATOR
