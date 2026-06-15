"""Bet categories, typed payload models, and validation (COMPLETION.md §8.1).

Pure domain code: enums + frozen payload dataclasses + parse/validate/serialize helpers, no I/O.
Payloads are stored as ``payload_json`` (TEXT) and validated against these typed models. The
knockout "no DRAW" rule is enforced at grading/UI time, not here — the model accepts any valid
:class:`WinnerSelection`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, assert_never


class BetCategory(StrEnum):
    """The five bet categories (COMPLETION.md §8.1)."""

    EXACT_SCORE = "EXACT_SCORE"
    FIRST_SCORER = "FIRST_SCORER"
    BTTS = "BTTS"
    WINNER = "WINNER"
    OVER_UNDER = "OVER_UNDER"


class BttsSelection(StrEnum):
    BOTH = "BOTH"
    ONLY_HOME = "ONLY_HOME"
    ONLY_AWAY = "ONLY_AWAY"
    NEITHER = "NEITHER"


class WinnerSelection(StrEnum):
    HOME = "HOME"
    DRAW = "DRAW"
    AWAY = "AWAY"


class OverUnderSelection(StrEnum):
    OVER = "OVER"
    UNDER = "UNDER"


@dataclass(frozen=True, slots=True)
class ExactScorePayload:
    home: int
    away: int


@dataclass(frozen=True, slots=True)
class FirstScorerPayload:
    player_id: int


@dataclass(frozen=True, slots=True)
class BttsPayload:
    sel: BttsSelection


@dataclass(frozen=True, slots=True)
class WinnerPayload:
    sel: WinnerSelection


@dataclass(frozen=True, slots=True)
class OverUnderPayload:
    sel: OverUnderSelection


BetPayload = ExactScorePayload | FirstScorerPayload | BttsPayload | WinnerPayload | OverUnderPayload


class InvalidBetPayload(ValueError):
    """Raised when a bet payload is missing fields or has invalid values."""


def _require_int(data: Mapping[str, Any], key: str, *, minimum: int) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise InvalidBetPayload(f"{key!r} must be an integer >= {minimum}")
    return value


def _require_enum[E: StrEnum](data: Mapping[str, Any], key: str, enum_cls: type[E]) -> E:
    value: Any = data.get(key)
    try:
        return enum_cls(value)
    except ValueError:
        allowed = [member.value for member in enum_cls]
        raise InvalidBetPayload(f"{key!r} must be one of {allowed}") from None


def parse_payload(category: BetCategory, data: Mapping[str, Any]) -> BetPayload:
    """Validate raw payload ``data`` for ``category`` into a typed payload (or raise)."""
    match category:
        case BetCategory.EXACT_SCORE:
            return ExactScorePayload(
                home=_require_int(data, "home", minimum=0),
                away=_require_int(data, "away", minimum=0),
            )
        case BetCategory.FIRST_SCORER:
            return FirstScorerPayload(player_id=_require_int(data, "player_id", minimum=1))
        case BetCategory.BTTS:
            return BttsPayload(sel=_require_enum(data, "sel", BttsSelection))
        case BetCategory.WINNER:
            return WinnerPayload(sel=_require_enum(data, "sel", WinnerSelection))
        case BetCategory.OVER_UNDER:
            return OverUnderPayload(sel=_require_enum(data, "sel", OverUnderSelection))
        case _:  # pragma: no cover - exhaustive over BetCategory
            assert_never(category)


def payload_to_dict(payload: BetPayload) -> dict[str, Any]:
    """Serialize a typed payload to a JSON-ready dict."""
    match payload:
        case ExactScorePayload(home=home, away=away):
            return {"home": home, "away": away}
        case FirstScorerPayload(player_id=player_id):
            return {"player_id": player_id}
        case BttsPayload(sel=sel):
            return {"sel": sel.value}
        case WinnerPayload(sel=sel):
            return {"sel": sel.value}
        case OverUnderPayload(sel=sel):
            return {"sel": sel.value}
        case _:  # pragma: no cover - exhaustive over BetPayload
            assert_never(payload)


def dump_payload(payload: BetPayload) -> str:
    """Serialize a payload to a compact JSON string for storage."""
    return json.dumps(payload_to_dict(payload), separators=(",", ":"))


def parse_payload_json(category: BetCategory, raw: str) -> BetPayload:
    """Parse and validate a stored ``payload_json`` string for ``category``."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise InvalidBetPayload("payload JSON must be an object")
    return parse_payload(category, data)
