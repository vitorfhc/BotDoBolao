"""Pure bet grading and the centralized points table (COMPLETION.md §8.1).

All grading is a pure function of :class:`MatchFacts` (the 90' result + goal timeline + advancing
team) — no I/O, no clock, no DB — so it is exhaustively unit-testable and deterministic. Settlement
builds :class:`MatchFacts` from the stored game and the provider's :class:`MatchResult`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import assert_never

from tigrinho.providers.base import GoalEvent, Stage

from .bets import (
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

# Single source of truth for per-category points (COMPLETION.md §8.1). Tune here only.
POINTS: dict[BetCategory, int] = {
    BetCategory.EXACT_SCORE: 5,
    BetCategory.FIRST_SCORER: 4,
    BetCategory.BTTS: 2,
    BetCategory.WINNER: 2,
    BetCategory.OVER_UNDER: 1,
}


@dataclass(frozen=True, slots=True)
class MatchFacts:
    """Everything grading needs about a finished game (90' result), as plain values."""

    stage: Stage
    home_team_id: int
    away_team_id: int
    home_goals_90: int
    away_goals_90: int
    goals: tuple[GoalEvent, ...]
    advancing_team_id: int | None


def first_genuine_scorer(goals: tuple[GoalEvent, ...]) -> int | None:
    """Player id of the earliest non-own-goal scorer within 90' (``None`` if there is none)."""
    for goal in sorted(goals, key=lambda g: g.minute):
        if not goal.is_own_goal and goal.minute <= 90:
            return goal.player_id
    return None


def _btts_pattern(facts: MatchFacts) -> BttsSelection:
    home_scored = facts.home_goals_90 > 0
    away_scored = facts.away_goals_90 > 0
    if home_scored and away_scored:
        return BttsSelection.BOTH
    if home_scored:
        return BttsSelection.ONLY_HOME
    if away_scored:
        return BttsSelection.ONLY_AWAY
    return BttsSelection.NEITHER


def _winner_outcome(facts: MatchFacts) -> WinnerSelection | None:
    """The winning :class:`WinnerSelection`, or ``None`` if no selection can win.

    Group stage uses the 90' 1X2 result. Knockout uses the advancing team (never a draw); a
    ``DRAW`` selection therefore always loses in knockout.
    """
    if facts.stage is Stage.KNOCKOUT:
        if facts.advancing_team_id == facts.home_team_id:
            return WinnerSelection.HOME
        if facts.advancing_team_id == facts.away_team_id:
            return WinnerSelection.AWAY
        return None
    if facts.home_goals_90 > facts.away_goals_90:
        return WinnerSelection.HOME
    if facts.home_goals_90 < facts.away_goals_90:
        return WinnerSelection.AWAY
    return WinnerSelection.DRAW


def is_winning_bet(payload: BetPayload, facts: MatchFacts) -> bool:
    """Whether ``payload`` wins given the 90' ``facts`` (pure)."""
    match payload:
        case ExactScorePayload(home=home, away=away):
            return facts.home_goals_90 == home and facts.away_goals_90 == away
        case FirstScorerPayload(player_id=player_id):
            scorer = first_genuine_scorer(facts.goals)
            return scorer is not None and scorer == player_id
        case BttsPayload(sel=sel):
            return _btts_pattern(facts) is sel
        case WinnerPayload(sel=sel):
            return _winner_outcome(facts) is sel
        case OverUnderPayload(sel=sel):
            total = facts.home_goals_90 + facts.away_goals_90
            if sel is OverUnderSelection.OVER:
                return total >= 3
            return total <= 2
        case _:  # pragma: no cover - exhaustive over BetPayload
            assert_never(payload)


def score_bet(category: BetCategory, payload: BetPayload, facts: MatchFacts) -> tuple[bool, int]:
    """Return ``(is_correct, points_awarded)`` — full points if correct, else 0."""
    correct = is_winning_bet(payload, facts)
    return correct, POINTS[category] if correct else 0
