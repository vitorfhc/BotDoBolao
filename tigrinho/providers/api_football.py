"""API-Football v3 provider — JSON to value-object mapping (COMPLETION.md §7.2).

This module holds the **pure** mapping functions (raw API JSON -> value objects). They have no
I/O, so they are exhaustively unit-testable with recorded JSON. The httpx-backed
``ApiFootballProvider`` class (which calls the endpoints and feeds these functions) is added on top.

Field paths, status codes, and endpoints verified against the live API-Football v3 docs (2026-06):
- Base ``https://v3.football.api-sports.io``; auth header ``x-apisports-key``.
- ``GET /fixtures`` -> ``response[].{fixture.{id,date,status.short}, league.round,
  teams.{home,away}.{id,name,winner}, score.{fulltime,extratime,penalty}.{home,away}}``.
- ``GET /fixtures/events`` -> ``response[].{time.{elapsed,extra}, team.id, player.{id,name},
  type, detail}``.
- ``GET /players/squads`` -> ``response[].{team.id, players[].{id,name,position}}``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from .base import Fixture, GameStatus, GoalEvent, MatchResult, SquadPlayer, Stage
from .budget import RequestBudget

DEFAULT_BASE_URL = "https://v3.football.api-sports.io"

# API-Football status.short -> normalized GameStatus (COMPLETION.md §7.2, live-verified).
_STATUS_MAP: dict[str, GameStatus] = {
    "TBD": GameStatus.SCHEDULED,
    "NS": GameStatus.SCHEDULED,
    "1H": GameStatus.LIVE,
    "HT": GameStatus.LIVE,
    "2H": GameStatus.LIVE,
    "ET": GameStatus.LIVE,
    "BT": GameStatus.LIVE,
    "P": GameStatus.LIVE,
    "SUSP": GameStatus.LIVE,
    "INT": GameStatus.LIVE,
    "LIVE": GameStatus.LIVE,
    "FT": GameStatus.FINISHED,
    "AET": GameStatus.FINISHED,
    "PEN": GameStatus.FINISHED,
    "PST": GameStatus.POSTPONED,
    "CANC": GameStatus.CANCELLED,
    "ABD": GameStatus.CANCELLED,
    "AWD": GameStatus.CANCELLED,
    "WO": GameStatus.CANCELLED,
}

# Event details that represent an actual goal (excludes "Missed Penalty", cards, subs, etc.).
_GOAL_DETAILS = frozenset({"Normal Goal", "Penalty", "Own Goal"})

# Substrings (lowercased round name) that mark a knockout round.
_KNOCKOUT_MARKERS = ("round of", "quarter", "semi", "final", "3rd place", "play-off", "playoff")


def _opt_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)


def normalize_status(short: str) -> GameStatus:
    """Map an API-Football ``status.short`` to a :class:`GameStatus` (unknown -> ``ValueError``)."""
    try:
        return _STATUS_MAP[short]
    except KeyError:
        raise ValueError(f"unknown API-Football status short code: {short!r}") from None


def parse_stage(round_name: str) -> Stage:
    """Classify a fixture ``league.round`` string as GROUP or KNOCKOUT."""
    lowered = round_name.lower()
    if "group" in lowered:
        return Stage.GROUP
    if any(marker in lowered for marker in _KNOCKOUT_MARKERS):
        return Stage.KNOCKOUT
    return Stage.GROUP


def parse_kickoff(date_str: str) -> datetime:
    """Parse an ISO-8601 fixture date into a tz-aware UTC datetime."""
    parsed = datetime.fromisoformat(date_str)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_fixture(item: Mapping[str, Any]) -> Fixture:
    """Map one ``/fixtures`` response item to a :class:`Fixture`."""
    fixture = item["fixture"]
    teams = item["teams"]
    return Fixture(
        fixture_id=int(fixture["id"]),
        stage=parse_stage(str(item["league"]["round"])),
        home_team_id=int(teams["home"]["id"]),
        home_team_name=str(teams["home"]["name"]),
        away_team_id=int(teams["away"]["id"]),
        away_team_name=str(teams["away"]["name"]),
        kickoff_utc=parse_kickoff(str(fixture["date"])),
        status=normalize_status(str(fixture["status"]["short"])),
    )


def parse_match_result(
    item: Mapping[str, Any], *, goals: tuple[GoalEvent, ...] = ()
) -> MatchResult:
    """Map one ``/fixtures`` item to a :class:`MatchResult` (90' = ``score.fulltime``).

    ``goals`` (the timeline from ``/fixtures/events``) is supplied separately by the caller.
    """
    fixture = item["fixture"]
    teams = item["teams"]
    fulltime = item["score"].get("fulltime") or {}
    home, away = teams["home"], teams["away"]
    advancing: int | None = None
    if home.get("winner") is True:
        advancing = int(home["id"])
    elif away.get("winner") is True:
        advancing = int(away["id"])
    return MatchResult(
        fixture_id=int(fixture["id"]),
        status=normalize_status(str(fixture["status"]["short"])),
        stage=parse_stage(str(item["league"]["round"])),
        home_goals_90=_opt_int(fulltime.get("home")),
        away_goals_90=_opt_int(fulltime.get("away")),
        goals=goals,
        advancing_team_id=advancing,
    )


def parse_goal_events(events: Sequence[Mapping[str, Any]]) -> tuple[GoalEvent, ...]:
    """Map ``/fixtures/events`` items to ordered goal events (keeps actual goals only).

    Cards/subs and "Missed Penalty" are dropped. Own goals and extra-time goals are **kept** with
    their flags/minutes; the domain layer applies the first-scorer rule (non-own-goal, minute<=90).
    """
    goals: list[GoalEvent] = []
    for event in events:
        if event.get("type") != "Goal":
            continue
        detail = event.get("detail")
        if detail not in _GOAL_DETAILS:
            continue
        time = event.get("time") or {}
        team = event.get("team") or {}
        player = event.get("player") or {}
        goals.append(
            GoalEvent(
                minute=int(time.get("elapsed") or 0),
                team_id=int(team["id"]),
                player_id=_opt_int(player.get("id")),
                player_name=_opt_str(player.get("name")),
                is_own_goal=detail == "Own Goal",
                is_penalty=detail == "Penalty",
            )
        )
    return tuple(goals)


def parse_squad_players(response: Sequence[Mapping[str, Any]]) -> list[SquadPlayer]:
    """Map a ``/players/squads`` response (one entry per team) to :class:`SquadPlayer` rows."""
    players: list[SquadPlayer] = []
    for entry in response:
        team_id = int(entry["team"]["id"])
        for player in entry.get("players") or []:
            players.append(
                SquadPlayer(
                    player_id=int(player["id"]),
                    team_id=team_id,
                    name=str(player["name"]),
                    position=_opt_str(player.get("position")),
                )
            )
    return players


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ApiFootballError(RuntimeError):
    """Raised when API-Football returns an error payload or a malformed response."""


class ApiFootballProvider:
    """:class:`FootballProvider` backed by API-Football v3 over httpx, gated by RequestBudget.

    Every network call goes through :class:`RequestBudget`, so the daily cap is enforced and a
    successful request increments the counter. Pass a preconfigured ``client`` (e.g. with a mock
    transport) for tests; otherwise an :class:`httpx.AsyncClient` is built with the auth header.
    """

    def __init__(
        self,
        *,
        league_id: int,
        season: int,
        budget: RequestBudget,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str = "",
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._league_id = league_id
        self._season = season
        self._budget = budget
        self._clock = clock
        self._client = (
            client
            if client is not None
            else httpx.AsyncClient(
                base_url=base_url,
                headers={"x-apisports-key": api_key},
                timeout=httpx.Timeout(15.0),
            )
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP client (call on bot shutdown)."""
        await self._client.aclose()

    async def _get(self, path: str, params: Mapping[str, Any]) -> list[Any]:
        async def call() -> Any:
            response = await self._client.get(path, params=dict(params))
            response.raise_for_status()
            return response.json()

        data = await self._budget.run(call)
        errors = data.get("errors")
        if errors:
            raise ApiFootballError(f"API-Football returned errors for {path}: {errors}")
        response_list = data.get("response")
        if not isinstance(response_list, list):
            raise ApiFootballError(f"API-Football response missing 'response' list for {path}")
        return response_list

    async def get_fixtures(self, window_hours: int) -> list[Fixture]:
        now = self._clock()
        end = now + timedelta(hours=window_hours)
        params = {
            "league": self._league_id,
            "season": self._season,
            "from": now.date().isoformat(),
            "to": end.date().isoformat(),
            "timezone": "UTC",
        }
        items = await self._get("/fixtures", params)
        fixtures = [parse_fixture(item) for item in items]
        return [fixture for fixture in fixtures if fixture.kickoff_utc <= end]

    async def get_live_results(self) -> list[MatchResult]:
        params = {"league": self._league_id, "season": self._season, "live": "all"}
        items = await self._get("/fixtures", params)
        # Belt-and-braces: keep only our league even if `live=all` ignores the league filter.
        return [
            parse_match_result(item)
            for item in items
            if int(item["league"]["id"]) == self._league_id
        ]

    async def get_match_result(self, fixture_id: int) -> MatchResult:
        fixtures = await self._get("/fixtures", {"id": fixture_id})
        if not fixtures:
            raise LookupError(f"API-Football has no fixture {fixture_id}")
        events = await self._get("/fixtures/events", {"fixture": fixture_id})
        goals = parse_goal_events(events)
        return parse_match_result(fixtures[0], goals=goals)

    async def get_squad(self, team_id: int) -> list[SquadPlayer]:
        response = await self._get("/players/squads", {"team": team_id})
        return parse_squad_players(response)
