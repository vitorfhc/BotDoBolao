"""Tests for provider value objects + the FootballProvider Protocol (COMPLETION.md §7.1)."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from tigrinho.providers.base import (
    Fixture,
    FootballProvider,
    GameStatus,
    GoalEvent,
    MatchResult,
    SquadPlayer,
    Stage,
)

KICKOFF = datetime(2026, 6, 15, 19, 0, tzinfo=UTC)


def test_enums_have_expected_values() -> None:
    assert Stage.GROUP == "GROUP"
    assert Stage.KNOCKOUT == "KNOCKOUT"
    assert {s.value for s in GameStatus} == {
        "SCHEDULED",
        "LIVE",
        "FINISHED",
        "POSTPONED",
        "CANCELLED",
        "VOID",
    }


def test_value_objects_construct_with_expected_fields() -> None:
    goal = GoalEvent(
        minute=23,
        team_id=10,
        player_id=7,
        player_name="Neymar",
        is_own_goal=False,
        is_penalty=False,
    )
    result = MatchResult(
        fixture_id=1,
        status=GameStatus.FINISHED,
        stage=Stage.GROUP,
        home_goals_90=2,
        away_goals_90=1,
        goals=(goal,),
        advancing_team_id=None,
    )
    fixture = Fixture(
        fixture_id=1,
        stage=Stage.GROUP,
        home_team_id=10,
        home_team_name="Brasil",
        away_team_id=20,
        away_team_name="Argentina",
        kickoff_utc=KICKOFF,
        status=GameStatus.SCHEDULED,
    )
    squad = SquadPlayer(player_id=7, team_id=10, name="Neymar", position="FW")

    assert result.goals[0].player_name == "Neymar"
    assert result.home_goals_90 == 2
    assert fixture.home_team_name == "Brasil"
    assert squad.position == "FW"


def test_value_objects_are_frozen() -> None:
    fixture = Fixture(
        fixture_id=1,
        stage=Stage.GROUP,
        home_team_id=10,
        home_team_name="Brasil",
        away_team_id=20,
        away_team_name="Argentina",
        kickoff_utc=KICKOFF,
        status=GameStatus.SCHEDULED,
    )
    field_name = "status"  # non-literal so this isn't a "use plain assignment" lint hit
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(fixture, field_name, GameStatus.LIVE)


def test_value_objects_support_equality() -> None:
    a = SquadPlayer(player_id=7, team_id=10, name="Neymar", position="FW")
    b = SquadPlayer(player_id=7, team_id=10, name="Neymar", position="FW")
    c = SquadPlayer(player_id=8, team_id=10, name="Vini", position="FW")
    assert a == b
    assert a != c


def test_optional_fields_accept_none() -> None:
    own_goal = GoalEvent(
        minute=40, team_id=20, player_id=None, player_name=None, is_own_goal=True, is_penalty=False
    )
    result = MatchResult(
        fixture_id=2,
        status=GameStatus.FINISHED,
        stage=Stage.KNOCKOUT,
        home_goals_90=0,
        away_goals_90=0,
        goals=(own_goal,),
        advancing_team_id=10,
    )
    assert result.goals[0].player_id is None
    assert result.advancing_team_id == 10


class _ConformingProvider:
    async def get_fixtures(self, window_hours: int) -> list[Fixture]:
        return []

    async def get_live_results(self) -> list[MatchResult]:
        return []

    async def get_match_result(self, fixture_id: int) -> MatchResult:
        raise NotImplementedError

    async def get_squad(self, team_id: int) -> list[SquadPlayer]:
        return []


def test_protocol_is_satisfied_by_conforming_class() -> None:
    assert isinstance(_ConformingProvider(), FootballProvider)
    assert not isinstance(object(), FootballProvider)
