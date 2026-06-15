"""Tests for pure settlement: grade every bet on a finished game, idempotently (§8.3, §16)."""

from __future__ import annotations

import pytest

from tigrinho.domain.bets import (
    BetCategory,
    BttsPayload,
    BttsSelection,
    ExactScorePayload,
    OverUnderPayload,
    OverUnderSelection,
    WinnerPayload,
    WinnerSelection,
    dump_payload,
)
from tigrinho.domain.scoring import MatchFacts
from tigrinho.domain.settlement import (
    BetInput,
    BetOutcome,
    match_facts_from_result,
    settle_game,
)
from tigrinho.providers.base import GameStatus, MatchResult, Stage

HOME_TEAM = 10
AWAY_TEAM = 20


def _facts() -> MatchFacts:
    # 2-1 group game.
    return MatchFacts(
        stage=Stage.GROUP,
        home_team_id=HOME_TEAM,
        away_team_id=AWAY_TEAM,
        home_goals_90=2,
        away_goals_90=1,
        advancing_team_id=None,
    )


def _mixed_bets() -> list[BetInput]:
    return [
        BetInput(1, BetCategory.EXACT_SCORE, dump_payload(ExactScorePayload(2, 1))),
        BetInput(2, BetCategory.EXACT_SCORE, dump_payload(ExactScorePayload(1, 1))),
        BetInput(5, BetCategory.BTTS, dump_payload(BttsPayload(BttsSelection.BOTH))),
        BetInput(6, BetCategory.WINNER, dump_payload(WinnerPayload(WinnerSelection.HOME))),
        BetInput(7, BetCategory.WINNER, dump_payload(WinnerPayload(WinnerSelection.DRAW))),
        BetInput(
            8, BetCategory.OVER_UNDER, dump_payload(OverUnderPayload(OverUnderSelection.OVER))
        ),
        BetInput(
            9, BetCategory.OVER_UNDER, dump_payload(OverUnderPayload(OverUnderSelection.UNDER))
        ),
    ]


def test_settle_game_grades_every_bet() -> None:
    outcomes = settle_game(_facts(), _mixed_bets())
    by_id = {o.bet_id: (o.is_correct, o.points_awarded) for o in outcomes}
    assert by_id == {
        1: (True, 5),  # exact 2-1
        2: (False, 0),  # exact 1-1
        5: (True, 2),  # BTTS both
        6: (True, 2),  # winner home
        7: (False, 0),  # winner draw
        8: (True, 1),  # over (total 3)
        9: (False, 0),  # under
    }


def test_settle_game_is_idempotent() -> None:
    facts, bets = _facts(), _mixed_bets()
    assert settle_game(facts, bets) == settle_game(facts, bets)


def test_settle_game_empty() -> None:
    assert settle_game(_facts(), []) == []


def test_malformed_payload_loses_without_crashing() -> None:
    bets = [BetInput(1, BetCategory.EXACT_SCORE, "{not valid json")]
    outcomes = settle_game(_facts(), bets)
    assert outcomes == [BetOutcome(bet_id=1, is_correct=False, points_awarded=0)]


def test_match_facts_from_result() -> None:
    result = MatchResult(
        fixture_id=100,
        status=GameStatus.FINISHED,
        stage=Stage.KNOCKOUT,
        home_goals_90=1,
        away_goals_90=1,
        advancing_team_id=AWAY_TEAM,
    )
    facts = match_facts_from_result(result, home_team_id=HOME_TEAM, away_team_id=AWAY_TEAM)
    assert facts.stage is Stage.KNOCKOUT
    assert facts.home_goals_90 == 1
    assert facts.advancing_team_id == AWAY_TEAM


def test_match_facts_from_result_requires_scores() -> None:
    result = MatchResult(
        fixture_id=100,
        status=GameStatus.FINISHED,
        stage=Stage.GROUP,
        home_goals_90=None,
        away_goals_90=None,
        advancing_team_id=None,
    )
    with pytest.raises(ValueError, match="90"):
        match_facts_from_result(result, home_team_id=HOME_TEAM, away_team_id=AWAY_TEAM)
