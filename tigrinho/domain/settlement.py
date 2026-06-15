"""Pure game settlement: grade every bet on a finished game (COMPLETION.md §8.3).

No I/O — the cog/CLI maps ORM rows to :class:`BetInput`, calls :func:`settle_game`, and writes the
returned :class:`BetOutcome` values back. Because it is a pure function of its inputs, settlement is
inherently **idempotent**: re-running for the same result reproduces identical outcomes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from tigrinho.providers.base import MatchResult

from .bets import BetCategory, InvalidBetPayload, parse_payload_json
from .scoring import MatchFacts, score_bet


@dataclass(frozen=True, slots=True)
class BetInput:
    """A bet to grade: its id, category, and stored ``payload_json``."""

    bet_id: int
    category: BetCategory
    payload_json: str


@dataclass(frozen=True, slots=True)
class BetOutcome:
    """The graded result for one bet."""

    bet_id: int
    is_correct: bool
    points_awarded: int


def match_facts_from_result(
    result: MatchResult, *, home_team_id: int, away_team_id: int
) -> MatchFacts:
    """Build grading :class:`MatchFacts` from a provider result + the stored team ids.

    Raises ``ValueError`` if the 90' score is missing (the caller should treat that as a
    not-yet-settleable / stuck game rather than grade it).
    """
    if result.home_goals_90 is None or result.away_goals_90 is None:
        raise ValueError(f"cannot settle fixture {result.fixture_id}: missing 90' score")
    return MatchFacts(
        stage=result.stage,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        home_goals_90=result.home_goals_90,
        away_goals_90=result.away_goals_90,
        goals=result.goals,
        advancing_team_id=result.advancing_team_id,
    )


def settle_game(facts: MatchFacts, bets: Sequence[BetInput]) -> list[BetOutcome]:
    """Grade every bet against ``facts``. A bet with an unparseable payload loses (0 points)."""
    outcomes: list[BetOutcome] = []
    for bet in bets:
        try:
            payload = parse_payload_json(bet.category, bet.payload_json)
        except InvalidBetPayload:
            outcomes.append(BetOutcome(bet_id=bet.bet_id, is_correct=False, points_awarded=0))
            continue
        correct, points = score_bet(bet.category, payload, facts)
        outcomes.append(BetOutcome(bet_id=bet.bet_id, is_correct=correct, points_awarded=points))
    return outcomes
