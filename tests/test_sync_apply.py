"""Tests for applying a SyncPlan to the DB: insert/reschedule/void games + void bets (§9.1)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from tigrinho.bot.sync_cog import apply_plan
from tigrinho.bot.sync_planning import SyncPlan
from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import Base
from tigrinho.db.repositories import BetRepository, GameRepository, PlayerRepository
from tigrinho.providers.base import Fixture, GameStatus, Stage

SP = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
KICK = datetime(2026, 6, 15, 19, 0, tzinfo=UTC)  # 16:00 SP


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    with create_session_factory(engine)() as s:
        yield s


def _fixture(
    fid: int, *, kickoff: datetime = KICK, status: GameStatus = GameStatus.SCHEDULED
) -> Fixture:
    return Fixture(
        fixture_id=fid,
        stage=Stage.GROUP,
        home_team_id=10,
        home_team_name="Brasil",
        away_team_id=20,
        away_team_name="Argentina",
        kickoff_utc=kickoff,
        status=status,
    )


def test_apply_new_inserts_game_with_local_time_and_hash(session: Session) -> None:
    counts = apply_plan(
        session, SyncPlan(new=[_fixture(1)], rescheduled=[], voided=[]), now=NOW, tz=SP
    )
    assert counts.new == 1
    game = GameRepository(session).get(1)
    assert game is not None
    assert game.status == "SCHEDULED"
    assert game.stage == "GROUP"
    assert game.home_team_name == "Brasil"
    assert game.kickoff_utc == KICK
    assert game.kickoff_local == KICK  # same instant (TZDateTime normalizes); display localizes
    assert len(game.match_hash) == 64


def test_apply_reschedule_updates_kickoff(session: Session) -> None:
    apply_plan(session, SyncPlan(new=[_fixture(1)], rescheduled=[], voided=[]), now=NOW, tz=SP)
    seeded = GameRepository(session).get(1)
    assert seeded is not None
    original_hash = seeded.match_hash
    later = KICK + timedelta(hours=2)
    counts = apply_plan(
        session,
        SyncPlan(new=[], rescheduled=[_fixture(1, kickoff=later)], voided=[]),
        now=NOW,
        tz=SP,
    )
    assert counts.rescheduled == 1
    game = GameRepository(session).get(1)
    assert game is not None
    assert game.kickoff_utc == later
    assert game.kickoff_local == later  # same instant
    assert game.match_hash != original_hash


def test_apply_void_sets_status_and_voids_bets(session: Session) -> None:
    apply_plan(session, SyncPlan(new=[_fixture(1)], rescheduled=[], voided=[]), now=NOW, tz=SP)
    PlayerRepository(session).get_or_create(100, "Vitor", now=NOW)
    bets = BetRepository(session)
    bets.upsert(fixture_id=1, player_discord_id=100, category="WINNER", payload_json="{}", now=NOW)

    cancelled = _fixture(1, status=GameStatus.CANCELLED)
    counts = apply_plan(
        session, SyncPlan(new=[], rescheduled=[], voided=[cancelled]), now=NOW, tz=SP
    )
    assert counts.voided == 1

    game = GameRepository(session).get(1)
    assert game is not None
    assert game.status == "VOID"
    assert game.settled_at == NOW
    voided_bet = bets.get_for(1, 100, "WINNER")
    assert voided_bet is not None
    assert voided_bet.points_awarded == 0
    assert voided_bet.is_correct is None
    assert voided_bet.settled_at == NOW


def test_apply_void_missing_game_is_noop(session: Session) -> None:
    counts = apply_plan(
        session,
        SyncPlan(new=[], rescheduled=[], voided=[_fixture(999, status=GameStatus.CANCELLED)]),
        now=NOW,
        tz=SP,
    )
    assert counts.voided == 1  # counted, but no row to touch
    assert GameRepository(session).get(999) is None
