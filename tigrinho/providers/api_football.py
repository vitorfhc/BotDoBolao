"""API-Football v3 provider — JSON to value-object mapping (COMPLETION.md §7.2).

This module holds the **pure** mapping functions (raw API JSON -> value objects). They have no
I/O, so they are exhaustively unit-testable with recorded JSON. The httpx-backed
``ApiFootballProvider`` class (which calls the endpoints and feeds these functions) is added on top.

Field paths, status codes, and endpoints verified against the live API-Football v3 docs (2026-06):
- Base ``https://v3.football.api-sports.io``; auth header ``x-apisports-key``.
- ``GET /fixtures`` -> ``response[].{fixture.{id,date,status.short}, league.round,
  teams.{home,away}.{id,name,winner}, goals.{home,away},
  score.{fulltime,extratime,penalty}.{home,away}}``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from .base import Fixture, GameStatus, MatchResult, Stage
from .budget import RequestBudget
from .retry import retry_async

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

# Substrings (lowercased round name) that mark a knockout round.
_KNOCKOUT_MARKERS = ("round of", "quarter", "semi", "final", "3rd place", "play-off", "playoff")


def _opt_int(value: Any) -> int | None:
    return None if value is None else int(value)


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


def parse_match_result(item: Mapping[str, Any]) -> MatchResult:
    """Map one ``/fixtures`` item to a :class:`MatchResult`.

    ``home_goals_90``/``away_goals_90`` come from ``score.fulltime`` (regulation, for settlement);
    ``home_goals``/``away_goals`` come from the top-level ``goals`` object (the current/live
    aggregate score, used for goal notifications — §9.3).
    """
    fixture = item["fixture"]
    teams = item["teams"]
    fulltime = item["score"].get("fulltime") or {}
    live = item.get("goals") or {}
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
        advancing_team_id=advancing,
        home_goals=_opt_int(live.get("home")),
        away_goals=_opt_int(live.get("away")),
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ApiFootballError(RuntimeError):
    """Raised when API-Football returns an error payload or a malformed response."""


# Transient HTTP failures worth retrying: network/timeout blips and server/rate-limit responses.
# Verified against the httpx 0.28 exception hierarchy (https://www.python-httpx.org/exceptions/):
# TransportError is the base for TimeoutException/ConnectError/ReadError; HTTPStatusError (raised
# by raise_for_status) carries the response, so we gate it on the status code.
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRY_STATUS
    return False


async def _default_sleep(delay: float) -> None:
    await asyncio.sleep(delay)


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
        max_retries: int = 2,
        retry_backoff: float = 0.5,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._league_id = league_id
        self._season = season
        self._budget = budget
        self._clock = clock
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._sleep = sleep if sleep is not None else _default_sleep
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

    async def _raw_get(self, path: str, params: dict[str, Any]) -> Any:
        response = await self._client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    async def _get(self, path: str, params: Mapping[str, Any]) -> list[Any]:
        params_dict = dict(params)

        async def attempt() -> Any:
            # Budget is re-checked before each attempt and increments only on success, so retried
            # (failed) attempts don't burn the daily counter.
            return await self._budget.run(lambda: self._raw_get(path, params_dict))

        data = await retry_async(
            attempt,
            retries=self._max_retries,
            backoff_base=self._retry_backoff,
            sleep=self._sleep,
            is_transient=_is_transient,
        )
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

    async def get_recent_results(self, lookback_hours: int) -> list[MatchResult]:
        # `live=all` returns ONLY in-play fixtures (finished games drop out immediately), so the
        # settlement path queries fixtures by date window instead: that returns every fixture with
        # its current status.short, including FT/AET/PEN. Verified 2026-06 against
        # https://www.api-football.com/documentation-v3 (fixtures: `live` vs `from`/`to`/`date`).
        now = self._clock()
        start = now - timedelta(hours=lookback_hours)
        params = {
            "league": self._league_id,
            "season": self._season,
            "from": start.date().isoformat(),
            "to": now.date().isoformat(),
            "timezone": "UTC",
        }
        items = await self._get("/fixtures", params)
        # Keep only our league even if the API ignores the league filter on a date query.
        return [
            parse_match_result(item)
            for item in items
            if int(item["league"]["id"]) == self._league_id
        ]

    async def get_match_result(self, fixture_id: int) -> MatchResult:
        fixtures = await self._get("/fixtures", {"id": fixture_id})
        if not fixtures:
            raise LookupError(f"API-Football has no fixture {fixture_id}")
        return parse_match_result(fixtures[0])
