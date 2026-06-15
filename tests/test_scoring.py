"""Exhaustive grading tests for the pure scoring layer (COMPLETION.md §8.1, §16)."""

from __future__ import annotations

import pytest

from tigrinho.domain.bets import (
    BetCategory,
    BetPayload,
    BttsPayload,
    BttsSelection,
    ExactScorePayload,
    OverUnderPayload,
    OverUnderSelection,
    WinnerPayload,
    WinnerSelection,
)
from tigrinho.domain.scoring import (
    POINTS,
    MatchFacts,
    is_winning_bet,
    score_bet,
)
from tigrinho.providers.base import Stage

HOME_TEAM = 10
AWAY_TEAM = 20


def _facts(
    *,
    stage: Stage = Stage.GROUP,
    home: int = 0,
    away: int = 0,
    advancing: int | None = None,
) -> MatchFacts:
    return MatchFacts(
        stage=stage,
        home_team_id=HOME_TEAM,
        away_team_id=AWAY_TEAM,
        home_goals_90=home,
        away_goals_90=away,
        advancing_team_id=advancing,
    )


# --- points table ---


def test_points_table() -> None:
    assert POINTS == {
        BetCategory.EXACT_SCORE: 5,
        BetCategory.BTTS: 2,
        BetCategory.WINNER: 2,
        BetCategory.OVER_UNDER: 1,
    }


# --- exact score ---


def test_exact_score() -> None:
    assert is_winning_bet(ExactScorePayload(2, 1), _facts(home=2, away=1)) is True
    assert is_winning_bet(ExactScorePayload(2, 1), _facts(home=1, away=1)) is False
    assert is_winning_bet(ExactScorePayload(0, 0), _facts(home=0, away=0)) is True


# --- both teams to score ---


@pytest.mark.parametrize(
    ("sel", "home", "away", "expected"),
    [
        (BttsSelection.BOTH, 1, 1, True),
        (BttsSelection.BOTH, 1, 0, False),
        (BttsSelection.ONLY_HOME, 2, 0, True),
        (BttsSelection.ONLY_HOME, 2, 1, False),
        (BttsSelection.ONLY_AWAY, 0, 1, True),
        (BttsSelection.NEITHER, 0, 0, True),
        (BttsSelection.NEITHER, 1, 0, False),
    ],
)
def test_btts(sel: BttsSelection, home: int, away: int, expected: bool) -> None:
    assert is_winning_bet(BttsPayload(sel), _facts(home=home, away=away)) is expected


# --- winner: group stage (1X2) ---


@pytest.mark.parametrize(
    ("sel", "home", "away", "expected"),
    [
        (WinnerSelection.HOME, 2, 1, True),
        (WinnerSelection.DRAW, 1, 1, True),
        (WinnerSelection.AWAY, 0, 1, True),
        (WinnerSelection.HOME, 1, 1, False),
        (WinnerSelection.DRAW, 2, 1, False),
    ],
)
def test_winner_group(sel: WinnerSelection, home: int, away: int, expected: bool) -> None:
    assert is_winning_bet(WinnerPayload(sel), _facts(home=home, away=away)) is expected


# --- winner: knockout (advancing team; never a draw) ---


def test_winner_knockout_advancing_team() -> None:
    # 90' draw 1-1, away advances on penalties
    facts = _facts(stage=Stage.KNOCKOUT, home=1, away=1, advancing=AWAY_TEAM)
    assert is_winning_bet(WinnerPayload(WinnerSelection.AWAY), facts) is True
    assert is_winning_bet(WinnerPayload(WinnerSelection.HOME), facts) is False
    assert is_winning_bet(WinnerPayload(WinnerSelection.DRAW), facts) is False  # draw never wins


def test_winner_knockout_home_advances() -> None:
    facts = _facts(stage=Stage.KNOCKOUT, home=2, away=1, advancing=HOME_TEAM)
    assert is_winning_bet(WinnerPayload(WinnerSelection.HOME), facts) is True


# --- over/under 2.5 (boundary at 2 and 3) ---


@pytest.mark.parametrize(
    ("sel", "home", "away", "expected"),
    [
        (OverUnderSelection.OVER, 2, 1, True),  # total 3
        (OverUnderSelection.OVER, 1, 1, False),  # total 2
        (OverUnderSelection.UNDER, 1, 1, True),  # total 2
        (OverUnderSelection.UNDER, 2, 1, False),  # total 3
        (OverUnderSelection.OVER, 3, 3, True),  # total 6
        (OverUnderSelection.UNDER, 0, 0, True),  # total 0
    ],
)
def test_over_under(sel: OverUnderSelection, home: int, away: int, expected: bool) -> None:
    assert is_winning_bet(OverUnderPayload(sel), _facts(home=home, away=away)) is expected


# --- score_bet (correct -> points, wrong -> 0) ---


def test_score_bet_awards_points_only_when_correct() -> None:
    correct: BetPayload = ExactScorePayload(2, 1)
    assert score_bet(BetCategory.EXACT_SCORE, correct, _facts(home=2, away=1)) == (True, 5)
    assert score_bet(BetCategory.EXACT_SCORE, correct, _facts(home=0, away=0)) == (False, 0)
    assert score_bet(
        BetCategory.OVER_UNDER, OverUnderPayload(OverUnderSelection.OVER), _facts(home=2, away=1)
    ) == (True, 1)
