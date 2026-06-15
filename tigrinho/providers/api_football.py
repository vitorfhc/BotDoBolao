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

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from .base import Fixture, GameStatus, GoalEvent, MatchResult, SquadPlayer, Stage

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
