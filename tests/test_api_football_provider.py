"""Tests for ApiFootballProvider — httpx wiring, budget, errors (offline via MockTransport)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import Base
from tigrinho.db.repositories import ApiUsageRepository
from tigrinho.providers.api_football import ApiFootballError, ApiFootballProvider
from tigrinho.providers.base import FootballProvider, GameStatus
from tigrinho.providers.budget import BudgetExceeded, RequestBudget

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def usage(tmp_path: Path) -> Iterator[ApiUsageRepository]:
    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    with create_session_factory(engine)() as session:
        yield ApiUsageRepository(session)


def _envelope(response_list: list[dict[str, Any]], errors: object = None) -> dict[str, Any]:
    return {"errors": errors if errors is not None else [], "response": response_list}


def _provider(
    usage: ApiUsageRepository,
    handler: Handler,
    *,
    cap: int = 100,
    max_retries: int = 2,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> ApiFootballProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test")
    budget = RequestBudget(usage, cap=cap, reset_tz=UTC, clock=lambda: NOW)
    return ApiFootballProvider(
        league_id=1,
        season=2026,
        budget=budget,
        client=client,
        clock=lambda: NOW,
        max_retries=max_retries,
        sleep=sleep,
    )


async def test_get_fixtures_maps_and_applies_window(usage: ApiUsageRepository) -> None:
    seen: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, dict(request.url.params)))
        items = [
            {
                "fixture": {
                    "id": 1,
                    "date": "2026-06-15T18:00:00+00:00",
                    "status": {"short": "NS"},
                },
                "league": {"id": 1, "round": "Group A"},
                "teams": {"home": {"id": 10, "name": "BRA"}, "away": {"id": 20, "name": "ARG"}},
            },
            {
                "fixture": {
                    "id": 2,
                    "date": "2026-06-20T18:00:00+00:00",
                    "status": {"short": "NS"},
                },
                "league": {"id": 1, "round": "Group A"},
                "teams": {"home": {"id": 30, "name": "FRA"}, "away": {"id": 40, "name": "GER"}},
            },
        ]
        return httpx.Response(200, json=_envelope(items))

    provider = _provider(usage, handler)
    fixtures = await provider.get_fixtures(48)  # window ends 2026-06-17 12:00 UTC
    assert [f.fixture_id for f in fixtures] == [1]  # fixture 2 is beyond the window
    assert seen[0][0].endswith("/fixtures")
    assert seen[0][1]["league"] == "1"
    assert usage.get_count(NOW.date()) == 1


async def test_get_recent_results_includes_finished_and_filters_league(
    usage: ApiUsageRepository,
) -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        items = [
            {  # finished game — MUST be returned (live=all would omit it)
                "fixture": {
                    "id": 1,
                    "date": "2026-06-15T10:00:00+00:00",
                    "status": {"short": "FT"},
                },
                "league": {"id": 1, "round": "Group A"},
                "teams": {
                    "home": {"id": 10, "name": "BRA", "winner": None},
                    "away": {"id": 20, "name": "ARG", "winner": None},
                },
                "score": {"fulltime": {"home": 2, "away": 1}},
            },
            {  # in-play game in our league
                "fixture": {
                    "id": 2,
                    "date": "2026-06-15T12:00:00+00:00",
                    "status": {"short": "1H"},
                },
                "league": {"id": 1, "round": "Group B"},
                "teams": {
                    "home": {"id": 30, "name": "FRA", "winner": None},
                    "away": {"id": 40, "name": "GER", "winner": None},
                },
                "score": {"fulltime": {"home": None, "away": None}},
            },
            {  # other league — filtered out
                "fixture": {
                    "id": 99,
                    "date": "2026-06-15T12:00:00+00:00",
                    "status": {"short": "FT"},
                },
                "league": {"id": 39, "round": "Premier League"},
                "teams": {
                    "home": {"id": 50, "name": "X", "winner": None},
                    "away": {"id": 60, "name": "Y", "winner": None},
                },
                "score": {"fulltime": {"home": 1, "away": 0}},
            },
        ]
        return httpx.Response(200, json=_envelope(items))

    provider = _provider(usage, handler)
    results = await provider.get_recent_results(24)
    assert [r.fixture_id for r in results] == [1, 2]  # league 39 filtered out
    finished = next(r for r in results if r.fixture_id == 1)
    assert finished.status is GameStatus.FINISHED  # finished games ARE returned, unlike live=all
    assert (finished.home_goals_90, finished.away_goals_90) == (2, 1)
    # Date-windowed query (from/to), not the in-play `live` feed.
    assert "live" not in seen[0]
    assert seen[0]["from"] == "2026-06-14"  # NOW (2026-06-15 12:00) minus 24h
    assert seen[0]["to"] == "2026-06-15"


async def test_retries_transient_5xx_then_succeeds(usage: ApiUsageRepository) -> None:
    calls = 0
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(503, json=_envelope([]))
        return httpx.Response(200, json=_envelope([]))

    async def sleep(d: float) -> None:
        slept.append(d)

    provider = _provider(usage, handler, max_retries=2, sleep=sleep)
    assert await provider.get_fixtures(48) == []
    assert calls == 3  # 503, 503, 200
    assert len(slept) == 2  # backed off before each retry
    assert usage.get_count(NOW.date()) == 1  # only the successful attempt burns the budget


async def test_does_not_retry_client_error_4xx(usage: ApiUsageRepository) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json=_envelope([]))

    async def sleep(d: float) -> None:
        raise AssertionError("a 4xx is not transient and must not be retried")

    provider = _provider(usage, handler, max_retries=2, sleep=sleep)
    with pytest.raises(httpx.HTTPStatusError):
        await provider.get_fixtures(48)
    assert calls == 1  # no retry on a client error


async def test_get_match_result_merges_events_and_consumes_two_requests(
    usage: ApiUsageRepository,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/fixtures/events"):
            events = [
                {
                    "time": {"elapsed": 10},
                    "team": {"id": 10},
                    "player": {"id": 7, "name": "Neymar"},
                    "type": "Goal",
                    "detail": "Normal Goal",
                }
            ]
            return httpx.Response(200, json=_envelope(events))
        fixture = {
            "fixture": {"id": 100, "date": "2026-06-15T12:00:00+00:00", "status": {"short": "FT"}},
            "league": {"id": 1, "round": "Final"},
            "teams": {
                "home": {"id": 10, "name": "BRA", "winner": True},
                "away": {"id": 20, "name": "ARG", "winner": False},
            },
            "score": {"fulltime": {"home": 1, "away": 0}},
        }
        return httpx.Response(200, json=_envelope([fixture]))

    provider = _provider(usage, handler)
    result = await provider.get_match_result(100)
    assert result.home_goals_90 == 1
    assert result.advancing_team_id == 10
    assert len(result.goals) == 1
    assert result.goals[0].player_name == "Neymar"
    assert usage.get_count(NOW.date()) == 2  # /fixtures + /fixtures/events


async def test_get_match_result_missing_fixture_raises(usage: ApiUsageRepository) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_envelope([]))

    provider = _provider(usage, handler)
    with pytest.raises(LookupError):
        await provider.get_match_result(404)


async def test_get_squad(usage: ApiUsageRepository) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        squads = [
            {
                "team": {"id": 10, "name": "BRA"},
                "players": [{"id": 7, "name": "Neymar", "position": "Attacker"}],
            }
        ]
        return httpx.Response(200, json=_envelope(squads))

    provider = _provider(usage, handler)
    squad = await provider.get_squad(10)
    assert [p.player_id for p in squad] == [7]


async def test_api_errors_in_body_raise(usage: ApiUsageRepository) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": {"requests": "limit reached"}, "response": []})

    provider = _provider(usage, handler)
    with pytest.raises(ApiFootballError):
        await provider.get_fixtures(48)


async def test_budget_exceeded_skips_http_call(usage: ApiUsageRepository) -> None:
    for _ in range(5):
        usage.increment(NOW.date())  # reach cap
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json=_envelope([]))

    provider = _provider(usage, handler, cap=5)
    with pytest.raises(BudgetExceeded):
        await provider.get_fixtures(48)
    assert called is False  # the request was never made


def test_satisfies_football_provider_protocol(usage: ApiUsageRepository) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_envelope([]))

    assert isinstance(_provider(usage, handler), FootballProvider)
