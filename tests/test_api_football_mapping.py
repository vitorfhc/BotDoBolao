"""Tests for API-Football v3 JSON -> value-object mapping (COMPLETION.md §7.2).

Field paths/structure verified against the live API-Football v3 docs (2026-06).
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

import pytest

from tigrinho.providers.api_football import (
    normalize_status,
    parse_fixture,
    parse_goal_events,
    parse_kickoff,
    parse_match_result,
    parse_squad_players,
    parse_stage,
)
from tigrinho.providers.base import GameStatus, Stage


@pytest.mark.parametrize(
    ("short", "expected"),
    [
        ("NS", GameStatus.SCHEDULED),
        ("TBD", GameStatus.SCHEDULED),
        ("1H", GameStatus.LIVE),
        ("HT", GameStatus.LIVE),
        ("ET", GameStatus.LIVE),
        ("P", GameStatus.LIVE),
        ("SUSP", GameStatus.LIVE),
        ("INT", GameStatus.LIVE),
        ("LIVE", GameStatus.LIVE),
        ("FT", GameStatus.FINISHED),
        ("AET", GameStatus.FINISHED),
        ("PEN", GameStatus.FINISHED),
        ("PST", GameStatus.POSTPONED),
        ("CANC", GameStatus.CANCELLED),
        ("ABD", GameStatus.CANCELLED),
        ("AWD", GameStatus.CANCELLED),
        ("WO", GameStatus.CANCELLED),
    ],
)
def test_normalize_status(short: str, expected: GameStatus) -> None:
    assert normalize_status(short) == expected


def test_normalize_status_unknown_raises() -> None:
    with pytest.raises(ValueError, match="ZZ"):
        normalize_status("ZZ")


@pytest.mark.parametrize(
    ("round_name", "expected"),
    [
        ("Group A", Stage.GROUP),
        ("Group Stage - 1", Stage.GROUP),
        ("Round of 16", Stage.KNOCKOUT),
        ("Round of 32", Stage.KNOCKOUT),
        ("Quarter-finals", Stage.KNOCKOUT),
        ("Semi-finals", Stage.KNOCKOUT),
        ("Final", Stage.KNOCKOUT),
        ("3rd Place Final", Stage.KNOCKOUT),
    ],
)
def test_parse_stage(round_name: str, expected: Stage) -> None:
    assert parse_stage(round_name) == expected


def test_parse_kickoff_converts_to_utc() -> None:
    assert parse_kickoff("2026-06-15T16:00:00-03:00").hour == 19
    assert parse_kickoff("2026-06-15T19:00:00+00:00").hour == 19
    assert parse_kickoff("2026-06-15T19:00:00Z").tzinfo == UTC


_SCHEDULED_FIXTURE: dict[str, Any] = {
    "fixture": {"id": 5, "date": "2026-06-15T16:00:00-03:00", "status": {"short": "NS"}},
    "league": {"id": 1, "season": 2026, "round": "Group C - 2"},
    "teams": {
        "home": {"id": 10, "name": "Brasil"},
        "away": {"id": 20, "name": "Argentina"},
    },
}


def test_parse_fixture() -> None:
    fixture = parse_fixture(_SCHEDULED_FIXTURE)
    assert fixture.fixture_id == 5
    assert fixture.kickoff_utc.hour == 19
    assert fixture.kickoff_utc.tzinfo == UTC
    assert fixture.stage is Stage.GROUP
    assert fixture.status is GameStatus.SCHEDULED
    assert fixture.home_team_name == "Brasil"
    assert fixture.away_team_id == 20


_KNOCKOUT_PENALTIES: dict[str, Any] = {
    "fixture": {"id": 100, "date": "2026-07-10T16:00:00-03:00", "status": {"short": "PEN"}},
    "league": {"id": 1, "season": 2026, "round": "Semi-finals"},
    "teams": {
        "home": {"id": 10, "name": "Brasil", "winner": False},
        "away": {"id": 20, "name": "Argentina", "winner": True},
    },
    "goals": {"home": 1, "away": 1},
    "score": {
        "halftime": {"home": 0, "away": 1},
        "fulltime": {"home": 1, "away": 1},
        "extratime": {"home": 0, "away": 0},
        "penalty": {"home": 3, "away": 4},
    },
}


def test_parse_match_result_uses_fulltime_not_et_or_penalty() -> None:
    result = parse_match_result(_KNOCKOUT_PENALTIES)
    assert result.fixture_id == 100
    assert result.status is GameStatus.FINISHED
    assert result.stage is Stage.KNOCKOUT
    assert result.home_goals_90 == 1  # score.fulltime, NOT penalty
    assert result.away_goals_90 == 1
    assert result.advancing_team_id == 20  # teams.away.winner == True
    assert result.goals == ()  # no events merged in


def test_parse_match_result_group_no_advancing() -> None:
    item: dict[str, Any] = {
        "fixture": {"id": 1, "date": "2026-06-15T16:00:00-03:00", "status": {"short": "FT"}},
        "league": {"round": "Group A - 1"},
        "teams": {
            "home": {"id": 10, "name": "Brasil", "winner": False},
            "away": {"id": 20, "name": "Argentina", "winner": False},
        },
        "goals": {"home": 1, "away": 1},
        "score": {"fulltime": {"home": 1, "away": 1}},
    }
    result = parse_match_result(item)
    assert result.advancing_team_id is None
    assert result.home_goals_90 == 1


def test_parse_match_result_includes_live_score() -> None:
    # The top-level `goals` object is the current/live aggregate score (API `goals.{home,away}`).
    result = parse_match_result(_KNOCKOUT_PENALTIES)
    assert result.home_goals == 1
    assert result.away_goals == 1


def test_parse_match_result_live_score_present_while_fulltime_null() -> None:
    # In-play fixture: `score.fulltime` is null, but `goals` carries the live score.
    item: dict[str, Any] = {
        "fixture": {"id": 2, "date": "2026-06-15T16:00:00-03:00", "status": {"short": "1H"}},
        "league": {"round": "Group A - 1"},
        "teams": {
            "home": {"id": 10, "name": "Brasil"},
            "away": {"id": 20, "name": "Argentina"},
        },
        "goals": {"home": 1, "away": 0},
        "score": {"fulltime": {"home": None, "away": None}},
    }
    result = parse_match_result(item)
    assert result.status is GameStatus.LIVE
    assert result.home_goals_90 is None  # regulation result not final yet
    assert result.away_goals_90 is None
    assert result.home_goals == 1  # live score available
    assert result.away_goals == 0


def test_parse_match_result_absent_goals_key_yields_none() -> None:
    # No top-level `goals` object at all (e.g. a not-started fixture) -> live score is None.
    item: dict[str, Any] = {
        "fixture": {"id": 3, "date": "2026-06-15T16:00:00-03:00", "status": {"short": "NS"}},
        "league": {"round": "Group A - 1"},
        "teams": {
            "home": {"id": 10, "name": "Brasil"},
            "away": {"id": 20, "name": "Argentina"},
        },
        "score": {},
    }
    result = parse_match_result(item)
    assert result.home_goals is None
    assert result.away_goals is None


_EVENTS: list[dict[str, Any]] = [
    {
        "time": {"elapsed": 10, "extra": None},
        "team": {"id": 10},
        "player": {"id": 7, "name": "Neymar"},
        "type": "Goal",
        "detail": "Normal Goal",
    },
    {
        "time": {"elapsed": 20, "extra": None},
        "team": {"id": 20},
        "player": {"id": 99, "name": "Own Guy"},
        "type": "Goal",
        "detail": "Own Goal",
    },
    {
        "time": {"elapsed": 30, "extra": None},
        "team": {"id": 10},
        "player": {"id": 8, "name": "Penalty Taker"},
        "type": "Goal",
        "detail": "Penalty",
    },
    {
        "time": {"elapsed": 40, "extra": None},
        "team": {"id": 20},
        "player": {"id": 50, "name": "Misser"},
        "type": "Goal",
        "detail": "Missed Penalty",
    },
    {
        "time": {"elapsed": 35, "extra": None},
        "team": {"id": 10},
        "player": {"id": 9, "name": "Booked"},
        "type": "Card",
        "detail": "Yellow Card",
    },
    {
        "time": {"elapsed": 105, "extra": None},
        "team": {"id": 10},
        "player": {"id": 11, "name": "ET Scorer"},
        "type": "Goal",
        "detail": "Normal Goal",
    },
]


def test_parse_goal_events_filters_and_flags() -> None:
    goals = parse_goal_events(_EVENTS)
    # Kept: Normal@10, Own@20, Penalty@30, Normal(ET)@105. Excluded: Missed Penalty, Card.
    assert [g.minute for g in goals] == [10, 20, 30, 105]
    assert goals[0].player_name == "Neymar"
    assert goals[0].is_own_goal is False
    assert goals[0].is_penalty is False
    assert goals[1].is_own_goal is True
    assert goals[2].is_penalty is True
    assert goals[3].minute == 105  # ET goal kept; domain applies the <=90 filter


def test_parse_goal_events_handles_missing_player() -> None:
    events: list[dict[str, Any]] = [
        {
            "time": {"elapsed": 50},
            "team": {"id": 10},
            "player": {"id": None, "name": None},
            "type": "Goal",
            "detail": "Normal Goal",
        }
    ]
    goals = parse_goal_events(events)
    assert goals[0].player_id is None
    assert goals[0].player_name is None


def test_parse_squad_players() -> None:
    response: list[dict[str, Any]] = [
        {
            "team": {"id": 10, "name": "Brasil"},
            "players": [
                {"id": 7, "name": "Neymar", "position": "Attacker"},
                {"id": 1, "name": "Alisson", "position": "Goalkeeper"},
            ],
        }
    ]
    players = parse_squad_players(response)
    assert len(players) == 2
    assert players[0].player_id == 7
    assert players[0].team_id == 10
    assert players[0].position == "Attacker"
