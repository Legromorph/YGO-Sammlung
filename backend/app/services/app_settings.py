from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting
from app.schemas import AppSettingsPayload

DEFAULT_APP_SETTINGS = {
    "preferred_currency": "EUR",
    "preferred_card_language": "de",
    "preferred_search_language": "de",
    "preferred_price_language": "de",
}

_SUPPORTED_CURRENCIES = {"EUR", "USD"}


def _normalize_currency(value: str | None) -> str:
    candidate = (value or "").strip().upper()
    return candidate if candidate in _SUPPORTED_CURRENCIES else DEFAULT_APP_SETTINGS["preferred_currency"]


def _normalize_language(value: str | None) -> str:
    candidate = (value or "").strip().lower()
    if candidate in {"de", "deu", "ger", "de-de"}:
        return "de"
    if candidate in {"en", "eng", "en-us", "en-gb"}:
        return "en"
    return candidate[:16] or "de"


async def get_app_settings(db: AsyncSession) -> AppSetting:
    result = await db.execute(select(AppSetting).order_by(AppSetting.id.asc()).limit(1))
    setting = result.scalar_one_or_none()
    if setting:
        return setting

    setting = AppSetting(**DEFAULT_APP_SETTINGS)
    db.add(setting)
    await db.commit()
    await db.refresh(setting)
    return setting


async def update_app_settings(db: AsyncSession, payload: AppSettingsPayload) -> AppSetting:
    setting = await get_app_settings(db)
    setting.preferred_currency = _normalize_currency(payload.preferred_currency)
    setting.preferred_card_language = _normalize_language(payload.preferred_card_language)
    setting.preferred_search_language = _normalize_language(payload.preferred_search_language)
    setting.preferred_price_language = _normalize_language(payload.preferred_price_language)
    await db.flush()
    return setting
