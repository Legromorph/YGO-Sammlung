from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import re
from typing import Any


class CanonicalCardKind(StrEnum):
    MONSTER = "monster"
    SPELL = "spell"
    TRAP = "trap"
    SKILL = "skill"
    TOKEN = "token"
    OTHER = "other"


MONSTER_ONLY_FIELDS = frozenset(
    {
        "attribute",
        "monster_type",
        "atk",
        "defense",
        "level",
        "rank",
        "link_rating",
        "link_arrows",
        "pendulum_scale",
        "pendulum_effect",
    }
)
SPELL_TRAP_ONLY_FIELDS = frozenset({"spell_trap_type"})
COMMON_METADATA_FIELDS = frozenset({"card_type", "card_kind", "subtype", "frame_type", "archetype"})

ALLOWED_METADATA_FIELDS_BY_KIND: dict[CanonicalCardKind, frozenset[str]] = {
    CanonicalCardKind.MONSTER: COMMON_METADATA_FIELDS | MONSTER_ONLY_FIELDS,
    CanonicalCardKind.SPELL: COMMON_METADATA_FIELDS | SPELL_TRAP_ONLY_FIELDS,
    CanonicalCardKind.TRAP: COMMON_METADATA_FIELDS | SPELL_TRAP_ONLY_FIELDS,
    CanonicalCardKind.SKILL: COMMON_METADATA_FIELDS,
    CanonicalCardKind.TOKEN: COMMON_METADATA_FIELDS,
    CanonicalCardKind.OTHER: COMMON_METADATA_FIELDS,
}

CARD_METADATA_FIELD_NAMES = (
    "card_type",
    "card_kind",
    "subtype",
    "frame_type",
    "attribute",
    "monster_type",
    "archetype",
    "atk",
    "defense",
    "level",
    "rank",
    "link_rating",
    "link_arrows",
    "pendulum_scale",
    "pendulum_effect",
    "spell_trap_type",
)

_SPELL_TRAP_TYPE_ALIASES = {
    "normal": "normal",
    "continuous": "continuous",
    "equip": "equip",
    "field": "field",
    "quickplay": "quick_play",
    "quick": "quick_play",
    "ritual": "ritual",
    "counter": "counter",
}


def _clean_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _normalized_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def canonical_card_kind(card_type: str | None, frame_type: str | None = None) -> CanonicalCardKind:
    combined = " ".join(filter(None, [_clean_text(card_type), _clean_text(frame_type)])).lower()
    if "spell" in combined:
        return CanonicalCardKind.SPELL
    if "trap" in combined:
        return CanonicalCardKind.TRAP
    if "skill" in combined:
        return CanonicalCardKind.SKILL
    if "token" in combined:
        return CanonicalCardKind.TOKEN
    if "monster" in combined:
        return CanonicalCardKind.MONSTER
    return CanonicalCardKind.OTHER


def normalize_spell_trap_type(value: str | None) -> str | None:
    cleaned = _clean_text(value)
    if not cleaned:
        return None
    token = _normalized_token(cleaned)
    return _SPELL_TRAP_TYPE_ALIASES.get(token, re.sub(r"[^a-z0-9]+", "_", cleaned.lower()).strip("_") or None)


def _clean_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean_arrows(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [text for entry in value if (text := _clean_text(entry))]


@dataclass(frozen=True, slots=True)
class NormalizedCardMetadata:
    card_type: str | None
    card_kind: CanonicalCardKind
    subtype: str | None
    frame_type: str | None
    attribute: str | None
    monster_type: str | None
    archetype: str | None
    atk: int | None
    defense: int | None
    level: int | None
    rank: int | None
    link_rating: int | None
    link_arrows: list[str]
    pendulum_scale: int | None
    pendulum_effect: str | None
    spell_trap_type: str | None

    def as_dict(self) -> dict[str, Any]:
        values = asdict(self)
        values["card_kind"] = self.card_kind.value
        return values


def apply_card_metadata(target: Any, metadata: NormalizedCardMetadata) -> None:
    for field_name, value in metadata.as_dict().items():
        setattr(target, field_name, value)


def normalize_card_metadata(
    *,
    card_type: str | None,
    subtype: str | None = None,
    frame_type: str | None = None,
    race: str | None = None,
    attribute: str | None = None,
    monster_type: str | None = None,
    archetype: str | None = None,
    atk: Any = None,
    defense: Any = None,
    level: Any = None,
    rank: Any = None,
    link_rating: Any = None,
    link_arrows: Any = None,
    pendulum_scale: Any = None,
    pendulum_effect: str | None = None,
    spell_trap_type: str | None = None,
) -> NormalizedCardMetadata:
    cleaned_card_type = _clean_text(card_type)
    cleaned_subtype = _clean_text(subtype)
    cleaned_frame_type = _clean_text(frame_type)
    kind = canonical_card_kind(cleaned_card_type, cleaned_frame_type)
    type_tokens = " ".join(filter(None, [cleaned_card_type, cleaned_subtype, cleaned_frame_type])).lower()

    is_monster = kind == CanonicalCardKind.MONSTER
    is_spell_or_trap = kind in {CanonicalCardKind.SPELL, CanonicalCardKind.TRAP}
    is_link = is_monster and "link" in type_tokens
    is_xyz = is_monster and "xyz" in type_tokens
    is_pendulum = is_monster and "pendulum" in type_tokens

    resolved_monster_type = _clean_text(monster_type) or _clean_text(race)
    resolved_spell_trap_type = _clean_text(spell_trap_type) or _clean_text(race)

    return NormalizedCardMetadata(
        card_type=cleaned_card_type,
        card_kind=kind,
        subtype=cleaned_subtype,
        frame_type=cleaned_frame_type,
        attribute=_clean_text(attribute) if is_monster else None,
        monster_type=resolved_monster_type if is_monster else None,
        archetype=_clean_text(archetype),
        atk=_clean_int(atk) if is_monster else None,
        defense=_clean_int(defense) if is_monster and not is_link else None,
        level=_clean_int(level) if is_monster and not is_xyz and not is_link else None,
        rank=_clean_int(rank) if is_xyz else None,
        link_rating=_clean_int(link_rating) if is_link else None,
        link_arrows=_clean_arrows(link_arrows) if is_link else [],
        pendulum_scale=_clean_int(pendulum_scale) if is_pendulum else None,
        pendulum_effect=_clean_text(pendulum_effect) if is_pendulum else None,
        spell_trap_type=normalize_spell_trap_type(resolved_spell_trap_type) if is_spell_or_trap else None,
    )
