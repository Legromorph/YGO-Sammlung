from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import logging
from typing import Any

import httpx

from app.config import settings
from app.time_utils import utc_now

logger = logging.getLogger(__name__)

SUPPORTED_CURRENCIES = {"EUR", "USD"}
TWO_DP = Decimal("0.01")
_RATE_CACHE_TTL = timedelta(hours=12)
_rate_cache: dict[tuple[str, str], tuple[Decimal, datetime]] = {}


def _normalize_currency(value: str | None) -> str:
    candidate = (value or "").strip().upper()
    return candidate if candidate in SUPPORTED_CURRENCIES else "EUR"


async def _fetch_rate(source_currency: str, target_currency: str) -> Decimal | None:
    if source_currency == target_currency:
        return Decimal("1")

    cache_key = (source_currency, target_currency)
    cached = _rate_cache.get(cache_key)
    if cached and cached[1] >= utc_now() - _RATE_CACHE_TTL:
        return cached[0]

    url = f"https://api.frankfurter.dev/v2/rate/{source_currency}/{target_currency}"
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            response = await client.get(url)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            rate = Decimal(str(data["rate"]))
    except Exception as exc:  # pragma: no cover - external provider fallback
        logger.warning("Currency conversion rate fetch failed for %s -> %s: %s", source_currency, target_currency, exc)
        return None

    _rate_cache[cache_key] = (rate, utc_now())
    if rate:
        _rate_cache[(target_currency, source_currency)] = ((Decimal("1") / rate).quantize(Decimal("0.0000001"), rounding=ROUND_HALF_UP), utc_now())
    return rate


async def convert_amount(
    amount: float | int | Decimal | None,
    source_currency: str | None,
    target_currency: str | None,
) -> Decimal | None:
    if amount is None:
        return None

    source = _normalize_currency(source_currency or target_currency)
    target = _normalize_currency(target_currency or source)
    decimal_amount = amount if isinstance(amount, Decimal) else Decimal(str(amount))

    if source == target:
        return decimal_amount.quantize(TWO_DP, rounding=ROUND_HALF_UP)

    rate = await _fetch_rate(source, target)
    if rate is None:
        return None

    return (decimal_amount * rate).quantize(TWO_DP, rounding=ROUND_HALF_UP)
