"""Provider-agnostic football data contract: value objects + Protocol (COMPLETION.md §7.1).

Providers return **value objects**, never raw JSON. These are immutable (frozen) dataclasses so
domain logic can treat them as plain values. The provider is responsible for normalizing the
upstream status vocabulary into :class:`GameStatus` and for ordering ``goals`` by minute ascending.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable


class Stage(StrEnum):
    """Tournament phase; drives the knockout winner-grading rule (COMPLETION.md §8.1)."""

    GROUP = "GROUP"
    KNOCKOUT = "KNOCKOUT"


class GameStatus(StrEnum):
    """Normalized game lifecycle status.

    Providers emit everything except ``VOID``, which is app-internal (a postponed/cancelled
    game whose bets have been voided — see COMPLETION.md §9.1).
    """

    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    FINISHED = "FINISHED"
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"
    VOID = "VOID"


@dataclass(frozen=True, slots=True)
class Fixture:
    """An upcoming/known fixture. ``kickoff_local`` and ``match_hash`` are derived by the app."""

    fixture_id: int
    stage: Stage
    home_team_id: int
    home_team_name: str
    away_team_id: int
    away_team_name: str
    kickoff_utc: datetime
    status: GameStatus


@dataclass(frozen=True, slots=True)
class MatchResult:
    """Live or final result.

    ``home_goals_90``/``away_goals_90``: the 90-minute regulation result (``score.fulltime``),
    used by settlement (§7.2). ``home_goals``/``away_goals``: the current/live aggregate score
    (API top-level ``goals``), used for goal notifications (§9.3); ``None`` if not supplied.

    ``advancing_team_id`` is set only for knockout fixtures (the side that progresses, derived
    from extra time / penalties).
    """

    fixture_id: int
    status: GameStatus
    stage: Stage
    home_goals_90: int | None
    away_goals_90: int | None
    advancing_team_id: int | None
    home_goals: int | None = None
    away_goals: int | None = None


@runtime_checkable
class FootballProvider(Protocol):
    """Async football data source. Implemented by ``ApiFootballProvider`` and ``FakeProvider``."""

    async def get_fixtures(self, window_hours: int) -> list[Fixture]:
        """Upcoming World Cup fixtures within ``window_hours`` of now."""
        ...

    async def get_recent_results(self, lookback_hours: int) -> list[MatchResult]:
        """Current results for every World Cup fixture that kicked off within ``lookback_hours``
        of now — **including finished ones**. The live-only feed omits finished matches, so the
        settlement path uses this date-windowed query (one call covers all in-play + finished)."""
        ...

    async def get_match_result(self, fixture_id: int) -> MatchResult:
        """Final 90' result for a single fixture."""
        ...
