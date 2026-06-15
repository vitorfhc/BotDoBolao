"""Tests for the data layer: schema creation, TZDateTime, FK + unique constraints."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine, inspect
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import ApiUsage, Base, Bet, Game, Player
from tigrinho.db.types import TZDateTime


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    eng = create_db_engine(str(tmp_path / "test.db"))
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(engine)


def _make_game(fixture_id: int = 1, kickoff: datetime | None = None) -> Game:
    k = kickoff or datetime(2026, 6, 15, 19, 0, tzinfo=UTC)
    return Game(
        fixture_id=fixture_id,
        match_hash="hash",
        stage="GROUP",
        home_team_id=10,
        home_team_name="Brasil",
        away_team_id=20,
        away_team_name="Argentina",
        kickoff_utc=k,
        kickoff_local=k,
        status="SCHEDULED",
        home_goals_90=None,
        away_goals_90=None,
        advancing_team_id=None,
        announced_at=None,
        settled_at=None,
    )


def _make_player(discord_id: int = 100) -> Player:
    return Player(
        discord_id=discord_id,
        display_name="Vitor",
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
    )


def _make_bet(fixture_id: int, player_discord_id: int, category: str, sel: str) -> Bet:
    now = datetime(2026, 6, 10, tzinfo=UTC)
    return Bet(
        fixture_id=fixture_id,
        player_discord_id=player_discord_id,
        category=category,
        payload_json=f'{{"sel":"{sel}"}}',
        created_at=now,
        updated_at=now,
        is_correct=None,
        points_awarded=None,
        settled_at=None,
    )


def test_create_all_builds_all_tables(engine: Engine) -> None:
    tables = set(inspect(engine).get_table_names())
    assert tables == {"players", "games", "bets", "api_usage"}


def test_player_and_game_roundtrip(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as s:
        s.add(_make_player(100))
        s.add(_make_game(1))
        s.commit()
    with session_factory() as s:
        player = s.get(Player, 100)
        game = s.get(Game, 1)
        assert player is not None
        assert player.display_name == "Vitor"
        assert game is not None
        assert game.home_team_name == "Brasil"
        assert game.status == "SCHEDULED"
        assert game.home_goals_90 is None


def test_tzdatetime_normalizes_to_utc_and_returns_aware(
    session_factory: sessionmaker[Session],
) -> None:
    sao_paulo = ZoneInfo("America/Sao_Paulo")
    kickoff = datetime(2026, 6, 15, 16, 0, tzinfo=sao_paulo)  # 19:00 UTC (UTC-3)
    with session_factory() as s:
        s.add(_make_game(2, kickoff=kickoff))
        s.commit()
    with session_factory() as s:
        game = s.get(Game, 2)
        assert game is not None
        assert game.kickoff_utc == kickoff  # equal as instants
        assert game.kickoff_utc.tzinfo == UTC
        assert game.kickoff_utc.utcoffset() == timedelta(0)
        assert game.kickoff_utc.hour == 19


def test_tzdatetime_rejects_naive_datetime() -> None:
    with pytest.raises(TypeError):
        TZDateTime().process_bind_param(datetime(2026, 1, 1, 12, 0), sqlite_dialect())


def test_bet_unique_constraint_one_per_category(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as s:
        s.add(_make_player(100))
        s.add(_make_game(1))
        s.commit()
    with session_factory() as s:
        s.add(_make_bet(1, 100, "WINNER", "HOME"))
        s.commit()
    with session_factory() as s:
        s.add(_make_bet(1, 100, "WINNER", "AWAY"))  # same (fixture, player, category)
        with pytest.raises(IntegrityError):
            s.commit()


def test_foreign_keys_enforced(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as s:
        s.add(_make_bet(999, 888, "WINNER", "HOME"))  # no such game/player
        with pytest.raises(IntegrityError):
            s.commit()


def test_api_usage_default_count(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as s:
        s.add(ApiUsage(budget_date=date(2026, 6, 15)))
        s.commit()
    with session_factory() as s:
        row = s.get(ApiUsage, date(2026, 6, 15))
        assert row is not None
        assert row.count == 0
