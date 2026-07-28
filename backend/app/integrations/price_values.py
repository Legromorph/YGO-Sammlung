from __future__ import annotations

import math
import re
from typing import Any


def parse_positive_price(value: Any) -> float | None:
    """Return a finite, strictly positive price or None."""
    try:
        if value in (None, ""):
            return None
        parsed = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(parsed) or parsed <= 0:
        return None
    return parsed


def parse_localized_price(value: str | None) -> float | None:
    if not value:
        return None

    normalized = re.sub(r"[^0-9,.\-]", "", value)
    if not normalized:
        return None

    if "," in normalized and "." in normalized:
        decimal_separator = "," if normalized.rfind(",") > normalized.rfind(".") else "."
        thousands_separator = "." if decimal_separator == "," else ","
        normalized = normalized.replace(thousands_separator, "").replace(decimal_separator, ".")
    elif "," in normalized:
        normalized = normalized.replace(",", ".")

    return parse_positive_price(normalized)
