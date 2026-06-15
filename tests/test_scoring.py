"""Exhaustive grading tests for the pure scoring layer (COMPLETION.md §8.1, §16)."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from tigrinho.domain.bets import (
    BetCategory,
    BetPayload,
    BttsPayload,
    BttsSelection,
    ExactScorePayload,
    FirstScorerPayload,
    OverUnderPayload,
    OverUnderSelection,
    WinnerPayload,
    WinnerSelection,
)
from tigrinho.domain.scoring import (
    POINTS,
    MatchFacts,
    first_genuine_scorer,
    is_winning_bet,
    score_bet,
)
from tigrinho.providers.base import GoalEvent, Stage

HOME_TEAM = 10
AWAY_TEAM = 20


def _goal(minute: int, team_id: int, player_id: int | None, *, own: bool = False) -> GoalEvent:
    return GoalEvent(
        minute=minute,
        team_id=team_id,
        player_id=player_id,
        player_name=None,
        is_own_goal=own,
        is_penalty=False,
    )


def _facts(
    *,
    stage: Stage = Stage.GROUP,
    home: int = 0,
    away: int = 0,
    goals: Sequence[GoalEvent] = (),
    advancing: int | None = None,
) -> MatchFacts:
    return MatchFacts(
        stage=stage,
        home_team_id=HOME_TEAM,
        away_team_id=AWAY_TEAM,
        home_goals_90=home,
        away_goals_90=away,
        goals=tuple(goals),
        advancing_team_id=advancing,
    )


# --- points table ---


def test_points_table() -> None:
    assert POINTS == {
        BetCategory.EXACT_SCORE: 5,
        BetCategory.FIRST_SCORER: 4,
        BetCategory.BTTS: 2,
        BetCategory.WINNER: 2,
        BetCategory.OVER_UNDER: 1,
    }


# --- exact score ---


def test_exact_score() -> None:
    assert is_winning_bet(ExactScorePayload(2, 1), _facts(home=2, away=1)) is True
    assert is_winning_bet(ExactScorePayload(2, 1), _facts(home=1, away=1)) is False
    assert is_winning_bet(ExactScorePayload(0, 0), _facts(home=0, away=0)) is True


# --- first scorer ---


def test_first_scorer_correct_player_wins() -> None:
    goals = [_goal(23, HOME_TEAM, 7), _goal(55, AWAY_TEAM, 8)]
    assert is_winning_bet(FirstScorerPayload(7), _facts(home=1, away=1, goals=goals)) is True
    assert is_winning_bet(FirstScorerPayload(8), _facts(home=1, away=1, goals=goals)) is False


def test_first_scorer_skips_own_goal() -> None:
    # 12' own goal (doesn't count), then 30' genuine scorer 7.
    goals = [_goal(12, AWAY_TEAM, 99, own=True), _goal(30, HOME_TEAM, 7)]
    assert is_winning_bet(FirstScorerPayload(7), _facts(home=1, away=1, goals=goals)) is True
    assert is_winning_bet(FirstScorerPayload(99), _facts(home=1, away=1, goals=goals)) is False


def test_first_scorer_none_on_goalless_or_own_only() -> None:
    assert first_genuine_scorer(()) is None
    assert first_genuine_scorer((_goal(40, AWAY_TEAM, 99, own=True),)) is None
    # everyone loses when there is no genuine 90' scorer
    assert is_winning_bet(FirstScorerPayload(7), _facts(home=0, away=0)) is False


def test_first_scorer_excludes_extra_time_goal() -> None:
    # only goal is in ET (minute 105) -> no genuine scorer within 90'
    goals = [_goal(105, HOME_TEAM, 7)]
    assert first_genuine_scorer(tuple(goals)) is None
    assert is_winning_bet(FirstScorerPayload(7), _facts(home=0, away=0, goals=goals)) is False


def test_first_scorer_orders_by_minute() -> None:
    # events provided out of order; earliest genuine goal is minute 10 (player 5)
    goals = [_goal(40, AWAY_TEAM, 8), _goal(10, HOME_TEAM, 5)]
    assert first_genuine_scorer(tuple(goals)) == 5


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
