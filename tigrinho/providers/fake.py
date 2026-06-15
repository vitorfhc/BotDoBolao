"""FakeProvider — a scripted, fully-offline :class:`FootballProvider` (COMPLETION.md §7.1).

Used by the test suite and by ``provider_mode: fake`` for local development. It never touches the
network: it simply returns whatever fixtures / results / squads it was given. ``get_fixtures``
ignores ``window_hours`` (callers script exactly the fixtures they want visible). Returned lists
are copies, so callers can mutate them without affecting the provider's state.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .base import Fixture, MatchResult, SquadPlayer


class FakeProvider:
    """In-memory provider whose responses are configured up front or via the ``set_*`` methods."""

    def __init__(
        self,
        *,
        fixtures: Iterable[Fixture] | None = None,
        recent_results: Iterable[MatchResult] | None = None,
        match_results: Iterable[MatchResult] | None = None,
        squads: Mapping[int, Iterable[SquadPlayer]] | None = None,
    ) -> None:
        self._fixtures: list[Fixture] = list(fixtures or [])
        self._recent_results: list[MatchResult] = list(recent_results or [])
        self._match_results: dict[int, MatchResult] = {
            m.fixture_id: m for m in (match_results or [])
        }
        self._squads: dict[int, list[SquadPlayer]] = {
            team_id: list(players) for team_id, players in (squads or {}).items()
        }

    # --- scripting helpers (for multi-step simulations) ---

    def set_fixtures(self, fixtures: Iterable[Fixture]) -> None:
        self._fixtures = list(fixtures)

    def set_recent_results(self, results: Iterable[MatchResult]) -> None:
        self._recent_results = list(results)

    def set_match_result(self, result: MatchResult) -> None:
        self._match_results[result.fixture_id] = result

    def set_squad(self, team_id: int, players: Iterable[SquadPlayer]) -> None:
        self._squads[team_id] = list(players)

    # --- FootballProvider Protocol ---

    async def get_fixtures(self, window_hours: int) -> list[Fixture]:
        return list(self._fixtures)

    async def get_recent_results(self, lookback_hours: int) -> list[MatchResult]:
        return list(self._recent_results)

    async def get_match_result(self, fixture_id: int) -> MatchResult:
        try:
            return self._match_results[fixture_id]
        except KeyError:
            raise LookupError(
                f"FakeProvider: no scripted match result for fixture {fixture_id}"
            ) from None

    async def get_squad(self, team_id: int) -> list[SquadPlayer]:
        return list(self._squads.get(team_id, []))
