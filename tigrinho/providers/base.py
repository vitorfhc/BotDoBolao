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
    """Live or final result. Scores are the **90-minute** regulation result (COMPLETION.md §7.2).

    ``advancing_team_id`` is set only for knockout fixtures (the side that progresses, derived
    from extra time / penalties).
    """

    fixture_id: int
    status: GameStatus
    stage: Stage
    home_goals_90: int | None
    away_goals_90: int | None
    advancing_team_id: int | None


@dataclass(frozen=True, slots=True)
class SquadPlayer:
    """A roster entry for first-scorer selection (cached). Distinct from the ORM row."""

    player_id: int
    team_id: int
    name: str
    position: str | None


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
        """Final result and goal timeline for a single fixture."""
        ...

    async def get_squad(self, team_id: int) -> list[SquadPlayer]:
        """A team's roster (used for first-scorer selection; cached)."""
        ...
