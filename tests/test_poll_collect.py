"""Tests for poll orchestration: collect_settlements + the stuck-game query (§9.2)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from tigrinho.bot.poll_cog import collect_settlements, should_poll
from tigrinho.config import Settings
from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import Base, Game
from tigrinho.db.repositories import BetRepository, GameRepository, PlayerRepository
from tigrinho.domain.bets import WinnerPayload, WinnerSelection, dump_payload
from tigrinho.providers.base import (
    Fixture,
    GameStatus,
    GoalEvent,
    MatchResult,
    SquadPlayer,
    Stage,
)
from tigrinho.providers.fake import FakeProvider

NOW = datetime(2026, 6, 15, 18, 0, tzinfo=UTC)


def _settings() -> Settings:
    return Settings(
        discord_token="tok",
        api_football_key="key",
        guild_id=111,
        announce_channel_id=222,
        tigrinhos_role_id=333,
        admin_user_id=444,
    )


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    with create_session_factory(engine)() as s:
        yield s


def _add_game(session: Session, fid: int, *, kickoff: datetime, settled: datetime | None) -> None:
    session.add(
        Game(
            fixture_id=fid,
            match_hash="h",
            stage="GROUP",
            home_team_id=10,
            home_team_name="Brasil",
            away_team_id=20,
            away_team_name="Argentina",
            kickoff_utc=kickoff,
            kickoff_local=kickoff,
            status="LIVE",
            home_goals_90=None,
            away_goals_90=None,
            advancing_team_id=None,
            first_scorer_player_id=None,
            announced_at=None,
            settled_at=settled,
        )
    )
    session.flush()


def _result(status: GameStatus, *, goals: tuple[GoalEvent, ...] = ()) -> MatchResult:
    return MatchResult(
        fixture_id=1,
        status=status,
        stage=Stage.GROUP,
        home_goals_90=2 if status is GameStatus.FINISHED else None,
        away_goals_90=1 if status is GameStatus.FINISHED else None,
        goals=goals,
        advancing_team_id=None,
    )


class _ExplodingProvider:
    async def get_fixtures(self, window_hours: int) -> list[Fixture]:
        raise AssertionError("should not be called")

    async def get_recent_results(self, lookback_hours: int) -> list[MatchResult]:
        raise AssertionError("get_recent_results must not run when there are no active games")

    async def get_match_result(self, fixture_id: int) -> MatchResult:
        raise AssertionError("should not be called")

    async def get_squad(self, team_id: int) -> list[SquadPlayer]:
        raise AssertionError("should not be called")


def test_list_stuck_returns_unsettled_past_window(session: Session) -> None:
    _add_game(session, 1, kickoff=NOW - timedelta(hours=5), settled=None)  # past 3h window -> stuck
    _add_game(session, 2, kickoff=NOW - timedelta(hours=1), settled=None)  # within window
    _add_game(session, 3, kickoff=NOW - timedelta(hours=8), settled=NOW)  # settled -> not stuck
    stuck = GameRepository(session).list_stuck(NOW, window_hours=3)
    assert [g.fixture_id for g in stuck] == [1]


async def test_collect_no_pollable_games_makes_no_api_call(session: Session) -> None:
    # An unsettled game past the settlement grace (>24h) is no longer pollable -> no provider call.
    _add_game(session, 1, kickoff=NOW - timedelta(hours=30), settled=None)
    result = await collect_settlements(session, _ExplodingProvider(), _settings(), now=NOW)
    assert result == []


async def test_collect_self_heals_overdue_game_within_grace(session: Session) -> None:
    # A game past the 3h match window but within the 24h grace (e.g. a knockout that ran to
    # penalties, or API status lag) still auto-settles once it's reported finished (§9.2).
    _add_game(session, 1, kickoff=NOW - timedelta(hours=5), settled=None)
    PlayerRepository(session).get_or_create(100, "Vitor", now=NOW)
    BetRepository(session).upsert(
        fixture_id=1,
        player_discord_id=100,
        category="WINNER",
        payload_json=dump_payload(WinnerPayload(WinnerSelection.HOME)),
        now=NOW,
    )
    provider = FakeProvider(
        recent_results=[_result(GameStatus.FINISHED)],
        match_results=[
            _result(GameStatus.FINISHED, goals=(GoalEvent(10, 10, 7, "N", False, False),))
        ],
    )
    settled = await collect_settlements(session, provider, _settings(), now=NOW)
    assert len(settled) == 1  # self-healed despite being past the match window
    game = GameRepository(session).get(1)
    assert game is not None and game.status == "FINISHED"


async def test_collect_settles_finished_active_game(session: Session) -> None:
    _add_game(session, 1, kickoff=NOW - timedelta(hours=2), settled=None)  # active
    PlayerRepository(session).get_or_create(100, "Vitor", now=NOW)
    BetRepository(session).upsert(
        fixture_id=1,
        player_discord_id=100,
        category="WINNER",
        payload_json=dump_payload(WinnerPayload(WinnerSelection.HOME)),
        now=NOW,
    )
    provider = FakeProvider(
        recent_results=[_result(GameStatus.FINISHED)],  # status feed: no goals
        match_results=[
            _result(GameStatus.FINISHED, goals=(GoalEvent(10, 10, 7, "N", False, False),))
        ],
    )
    settled = await collect_settlements(session, provider, _settings(), now=NOW)
    assert len(settled) == 1
    assert settled[0].players[0].total_points == 2  # WINNER HOME correct
    game = GameRepository(session).get(1)
    assert game is not None and game.status == "FINISHED"


async def test_collect_live_game_updates_status_without_settling(session: Session) -> None:
    _add_game(session, 1, kickoff=NOW - timedelta(hours=1), settled=None)  # active
    provider = FakeProvider(recent_results=[_result(GameStatus.LIVE)])
    settled = await collect_settlements(session, provider, _settings(), now=NOW)
    assert settled == []
    game = GameRepository(session).get(1)
    assert game is not None and game.status == "LIVE" and game.settled_at is None


def test_should_poll_true_when_a_game_is_in_the_match_window() -> None:
    # A live-window game is polled every cycle, even if we just polled a moment ago.
    assert (
        should_poll(
            pollable_kickoffs=[NOW - timedelta(hours=1)],
            now=NOW,
            last_poll=NOW - timedelta(seconds=30),
            match_window_hours=3,
            stuck_recheck_minutes=15,
        )
        is True
    )


def test_should_poll_false_when_nothing_pollable() -> None:
    assert (
        should_poll(
            pollable_kickoffs=[],
            now=NOW,
            last_poll=None,
            match_window_hours=3,
            stuck_recheck_minutes=15,
        )
        is False
    )


def test_should_poll_throttles_overdue_games_between_rechecks() -> None:
    overdue = [NOW - timedelta(hours=5)]  # past the 3h window but within grace

    def poll(last_poll: datetime | None) -> bool:
        return should_poll(
            pollable_kickoffs=overdue,
            now=NOW,
            last_poll=last_poll,
            match_window_hours=3,
            stuck_recheck_minutes=15,
        )

    assert poll(NOW - timedelta(minutes=5)) is False  # recently polled -> wait
    assert poll(NOW - timedelta(minutes=20)) is True  # recheck interval elapsed -> poll
    assert poll(None) is True  # never polled these overdue games -> poll
