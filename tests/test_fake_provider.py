"""Tests for FakeProvider — the scripted, offline provider for tests and local dev."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tigrinho.providers.base import (
    Fixture,
    FootballProvider,
    GameStatus,
    MatchResult,
    SquadPlayer,
    Stage,
)
from tigrinho.providers.fake import FakeProvider

KICK = datetime(2026, 6, 15, 19, 0, tzinfo=UTC)


def _fixture(fid: int = 1) -> Fixture:
    return Fixture(
        fixture_id=fid,
        stage=Stage.GROUP,
        home_team_id=10,
        home_team_name="Brasil",
        away_team_id=20,
        away_team_name="Argentina",
        kickoff_utc=KICK,
        status=GameStatus.SCHEDULED,
    )


def _result(fid: int = 1) -> MatchResult:
    return MatchResult(
        fixture_id=fid,
        status=GameStatus.FINISHED,
        stage=Stage.GROUP,
        home_goals_90=2,
        away_goals_90=1,
        goals=(),
        advancing_team_id=None,
    )


async def test_get_fixtures_returns_scripted() -> None:
    provider = FakeProvider(fixtures=[_fixture(1), _fixture(2)])
    fixtures = await provider.get_fixtures(48)
    assert [f.fixture_id for f in fixtures] == [1, 2]


async def test_get_live_results_returns_scripted() -> None:
    provider = FakeProvider(live_results=[_result(1)])
    assert [r.fixture_id for r in await provider.get_live_results()] == [1]


async def test_get_match_result_by_id() -> None:
    provider = FakeProvider(match_results=[_result(5)])
    result = await provider.get_match_result(5)
    assert result.fixture_id == 5
    assert result.home_goals_90 == 2


async def test_get_match_result_missing_raises() -> None:
    provider = FakeProvider()
    with pytest.raises(LookupError):
        await provider.get_match_result(99)


async def test_get_squad_by_team_and_unknown_is_empty() -> None:
    neymar = SquadPlayer(player_id=7, team_id=10, name="Neymar", position="FW")
    provider = FakeProvider(squads={10: [neymar]})
    assert [s.player_id for s in await provider.get_squad(10)] == [7]
    assert await provider.get_squad(999) == []


async def test_setters_update_outputs() -> None:
    provider = FakeProvider()
    provider.set_live_results([_result(1)])
    assert len(await provider.get_live_results()) == 1
    provider.set_match_result(_result(2))
    assert (await provider.get_match_result(2)).fixture_id == 2
    provider.set_fixtures([_fixture(3)])
    assert [f.fixture_id for f in await provider.get_fixtures(1)] == [3]
    provider.set_squad(20, [SquadPlayer(player_id=8, team_id=20, name="Messi", position=None)])
    assert [s.player_id for s in await provider.get_squad(20)] == [8]


async def test_returned_lists_are_copies() -> None:
    provider = FakeProvider(fixtures=[_fixture(1)])
    got = await provider.get_fixtures(48)
    got.append(_fixture(2))
    assert len(await provider.get_fixtures(48)) == 1  # internal state untouched


def test_satisfies_football_provider_protocol() -> None:
    assert isinstance(FakeProvider(), FootballProvider)
