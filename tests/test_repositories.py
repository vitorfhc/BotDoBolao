"""Tests for the typed CRUD repositories (players, games, bets)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import Base, Bet, Game
from tigrinho.db.repositories import BetRepository, GameRepository, PlayerRepository


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with factory() as s:
        yield s


def _game(fixture_id: int, kickoff: datetime, *, settled: datetime | None = None) -> Game:
    return Game(
        fixture_id=fixture_id,
        match_hash=f"h{fixture_id}",
        stage="GROUP",
        home_team_id=10,
        home_team_name="Brasil",
        away_team_id=20,
        away_team_name="Argentina",
        kickoff_utc=kickoff,
        kickoff_local=kickoff,
        status="SCHEDULED",
        home_goals_90=None,
        away_goals_90=None,
        advancing_team_id=None,
        announced_at=None,
        settled_at=settled,
    )


NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


# --- PlayerRepository ---------------------------------------------------------


def test_player_get_missing_returns_none(session: Session) -> None:
    assert PlayerRepository(session).get(999) is None


def test_player_get_or_create_creates_then_returns_same_row(session: Session) -> None:
    repo = PlayerRepository(session)
    created = repo.get_or_create(100, "Vitor", now=NOW)
    assert created.discord_id == 100
    assert created.created_at == NOW
    again = repo.get_or_create(100, "Vitor Renamed", now=NOW + timedelta(days=1))
    assert again.discord_id == 100
    assert again.created_at == NOW  # creation time is stable
    assert again.display_name == "Vitor Renamed"  # display name refreshes
    assert session.scalar(select(func.count()).select_from(type(created))) == 1


# --- GameRepository -----------------------------------------------------------


def test_game_add_and_get(session: Session) -> None:
    repo = GameRepository(session)
    repo.add(_game(1, NOW + timedelta(hours=5)))
    fetched = repo.get(1)
    assert fetched is not None
    assert fetched.home_team_name == "Brasil"
    assert repo.get(404) is None


def test_game_list_open_only_future_unsettled_sorted(session: Session) -> None:
    repo = GameRepository(session)
    repo.add(_game(1, NOW + timedelta(hours=5)))  # open
    repo.add(_game(2, NOW - timedelta(hours=1)))  # already started -> closed
    repo.add(_game(3, NOW + timedelta(hours=2)))  # open, earlier
    repo.add(_game(4, NOW + timedelta(hours=9), settled=NOW))  # settled -> excluded
    open_ids = [g.fixture_id for g in repo.list_open(NOW)]
    assert open_ids == [3, 1]  # sorted by kickoff ascending


def test_game_list_upcoming_within_window_future_unsettled_sorted(session: Session) -> None:
    repo = GameRepository(session)
    repo.add(_game(1, NOW + timedelta(hours=5)))  # within 24h -> included
    repo.add(_game(2, NOW - timedelta(hours=1)))  # already started -> excluded
    repo.add(_game(3, NOW + timedelta(hours=2)))  # within 24h, earlier
    repo.add(_game(4, NOW + timedelta(hours=30)))  # beyond 24h -> excluded
    repo.add(_game(5, NOW + timedelta(hours=3), settled=NOW))  # settled -> excluded
    upcoming_ids = [g.fixture_id for g in repo.list_upcoming(NOW, within_hours=24)]
    assert upcoming_ids == [3, 1]  # sorted by kickoff ascending


def test_game_list_active_within_window_and_unsettled(session: Session) -> None:
    repo = GameRepository(session)
    repo.add(_game(1, NOW + timedelta(hours=1)))  # not kicked off yet -> not active
    repo.add(_game(2, NOW - timedelta(hours=1)))  # kicked off, within 3h window -> active
    repo.add(_game(3, NOW - timedelta(hours=5)))  # outside 3h window -> not active
    repo.add(_game(4, NOW - timedelta(hours=2), settled=NOW))  # settled -> excluded
    active_ids = {g.fixture_id for g in repo.list_active(NOW, window_hours=3)}
    assert active_ids == {2}


def test_game_list_active_and_stuck_split_at_the_grace(session: Session) -> None:
    # Self-heal contract: the cog passes the settlement grace as the window, so overdue games
    # (past the match window) stay pollable until the grace expires; past it they're "stuck"
    # and the admin is alerted (COMPLETION.md §9.2).
    repo = GameRepository(session)
    repo.add(_game(1, NOW - timedelta(hours=5)))  # overdue vs a 3h match window...
    repo.add(_game(2, NOW - timedelta(hours=30)))  # ...and past a 24h grace
    pollable = {g.fixture_id for g in repo.list_active(NOW, window_hours=24)}
    expired = {g.fixture_id for g in repo.list_stuck(NOW, window_hours=24)}
    assert pollable == {1}  # still within the 24h grace -> keep auto-settling
    assert expired == {2}  # outlived the grace -> give up + alert


# --- BetRepository ------------------------------------------------------------


@pytest.fixture
def seeded(session: Session) -> Session:
    PlayerRepository(session).get_or_create(100, "Vitor", now=NOW)
    PlayerRepository(session).get_or_create(200, "Ana", now=NOW)
    GameRepository(session).add(_game(1, NOW + timedelta(hours=5)))
    return session


def test_bet_upsert_creates_then_overwrites_same_key(seeded: Session) -> None:
    repo = BetRepository(seeded)
    bet = repo.upsert(
        fixture_id=1,
        player_discord_id=100,
        category="WINNER",
        payload_json='{"sel":"HOME"}',
        now=NOW,
    )
    assert bet.created_at == NOW
    later = NOW + timedelta(hours=1)
    bet2 = repo.upsert(
        fixture_id=1,
        player_discord_id=100,
        category="WINNER",
        payload_json='{"sel":"AWAY"}',
        now=later,
    )
    assert bet2.id == bet.id  # same row, not a new bet
    assert bet2.payload_json == '{"sel":"AWAY"}'
    assert bet2.created_at == NOW  # unchanged
    assert bet2.updated_at == later
    assert seeded.scalar(select(func.count()).select_from(Bet)) == 1


def test_bet_get_for(seeded: Session) -> None:
    repo = BetRepository(seeded)
    repo.upsert(
        fixture_id=1, player_discord_id=100, category="BTTS", payload_json='{"sel":"BOTH"}', now=NOW
    )
    found = repo.get_for(1, 100, "BTTS")
    assert found is not None
    assert found.payload_json == '{"sel":"BOTH"}'
    assert repo.get_for(1, 100, "WINNER") is None


def test_bet_list_for_player_and_game(seeded: Session) -> None:
    repo = BetRepository(seeded)
    repo.upsert(fixture_id=1, player_discord_id=100, category="WINNER", payload_json="{}", now=NOW)
    repo.upsert(fixture_id=1, player_discord_id=100, category="BTTS", payload_json="{}", now=NOW)
    repo.upsert(fixture_id=1, player_discord_id=200, category="WINNER", payload_json="{}", now=NOW)
    assert {b.category for b in repo.list_for_player(100)} == {"WINNER", "BTTS"}
    assert len(repo.list_for_game(1)) == 3


def test_bet_delete(seeded: Session) -> None:
    repo = BetRepository(seeded)
    bet = repo.upsert(
        fixture_id=1, player_discord_id=100, category="WINNER", payload_json="{}", now=NOW
    )
    repo.delete(bet)
    seeded.flush()
    assert repo.get_for(1, 100, "WINNER") is None
