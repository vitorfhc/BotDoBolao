"""Tests for domain bet categories, payload models, and validation (COMPLETION.md §8.1)."""

from __future__ import annotations

import pytest

from tigrinho.domain.bets import (
    BetCategory,
    BetPayload,
    BttsPayload,
    BttsSelection,
    ExactScorePayload,
    FirstScorerPayload,
    InvalidBetPayload,
    OverUnderPayload,
    OverUnderSelection,
    WinnerPayload,
    WinnerSelection,
    dump_payload,
    parse_payload,
    parse_payload_json,
    payload_to_dict,
)


def test_category_and_selection_enum_values() -> None:
    assert {c.value for c in BetCategory} == {
        "EXACT_SCORE",
        "FIRST_SCORER",
        "BTTS",
        "WINNER",
        "OVER_UNDER",
    }
    assert {s.value for s in BttsSelection} == {"BOTH", "ONLY_HOME", "ONLY_AWAY", "NEITHER"}
    assert {s.value for s in WinnerSelection} == {"HOME", "DRAW", "AWAY"}
    assert {s.value for s in OverUnderSelection} == {"OVER", "UNDER"}


def test_parse_exact_score() -> None:
    payload = parse_payload(BetCategory.EXACT_SCORE, {"home": 2, "away": 1})
    assert payload == ExactScorePayload(home=2, away=1)


def test_parse_exact_score_allows_zero() -> None:
    assert parse_payload(BetCategory.EXACT_SCORE, {"home": 0, "away": 0}) == ExactScorePayload(0, 0)


@pytest.mark.parametrize(
    "data",
    [
        {"home": 2},  # missing away
        {"home": -1, "away": 0},  # negative
        {"home": 1.5, "away": 0},  # not int
        {"home": True, "away": 0},  # bool is not a valid score
        {"home": "2", "away": "1"},  # string
    ],
)
def test_parse_exact_score_invalid(data: dict[str, object]) -> None:
    with pytest.raises(InvalidBetPayload):
        parse_payload(BetCategory.EXACT_SCORE, data)


def test_parse_first_scorer() -> None:
    assert parse_payload(BetCategory.FIRST_SCORER, {"player_id": 7}) == FirstScorerPayload(7)


@pytest.mark.parametrize("data", [{}, {"player_id": 0}, {"player_id": -3}, {"player_id": "x"}])
def test_parse_first_scorer_invalid(data: dict[str, object]) -> None:
    with pytest.raises(InvalidBetPayload):
        parse_payload(BetCategory.FIRST_SCORER, data)


def test_parse_btts_winner_over_under() -> None:
    assert parse_payload(BetCategory.BTTS, {"sel": "BOTH"}) == BttsPayload(BttsSelection.BOTH)
    assert parse_payload(BetCategory.WINNER, {"sel": "DRAW"}) == WinnerPayload(WinnerSelection.DRAW)
    assert parse_payload(BetCategory.OVER_UNDER, {"sel": "OVER"}) == OverUnderPayload(
        OverUnderSelection.OVER
    )


@pytest.mark.parametrize(
    ("category", "data"),
    [
        (BetCategory.BTTS, {"sel": "MAYBE"}),
        (BetCategory.BTTS, {}),
        (BetCategory.WINNER, {"sel": "home"}),  # case-sensitive
        (BetCategory.OVER_UNDER, {"sel": None}),
    ],
)
def test_parse_selection_invalid(category: BetCategory, data: dict[str, object]) -> None:
    with pytest.raises(InvalidBetPayload):
        parse_payload(category, data)


def test_payload_to_dict_round_trips() -> None:
    cases: list[tuple[BetCategory, BetPayload]] = [
        (BetCategory.EXACT_SCORE, ExactScorePayload(3, 2)),
        (BetCategory.FIRST_SCORER, FirstScorerPayload(99)),
        (BetCategory.BTTS, BttsPayload(BttsSelection.NEITHER)),
        (BetCategory.WINNER, WinnerPayload(WinnerSelection.AWAY)),
        (BetCategory.OVER_UNDER, OverUnderPayload(OverUnderSelection.UNDER)),
    ]
    for category, payload in cases:
        as_dict = payload_to_dict(payload)
        assert parse_payload(category, as_dict) == payload


def test_json_round_trip() -> None:
    payload = WinnerPayload(WinnerSelection.HOME)
    raw = dump_payload(payload)
    assert parse_payload_json(BetCategory.WINNER, raw) == payload


def test_parse_payload_json_rejects_non_object() -> None:
    with pytest.raises(InvalidBetPayload):
        parse_payload_json(BetCategory.WINNER, "[1, 2]")
