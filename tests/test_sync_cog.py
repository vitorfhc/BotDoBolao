"""Tests for the sync orchestration (collect_sync_messages) + SyncCog wiring (§9.1)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from tigrinho.bot.sync_cog import SyncCog, collect_sync_messages
from tigrinho.config import Settings
from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import Base
from tigrinho.db.repositories import BetRepository, GameRepository, PlayerRepository
from tigrinho.providers.base import Fixture, GameStatus, Stage
from tigrinho.providers.fake import FakeProvider

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
KICK = datetime(2026, 6, 15, 19, 0, tzinfo=UTC)


def _settings() -> Settings:
    return Settings(
        discord_token="tok",
        api_football_key="key",
        guild_id=111,
        announce_channel_id=222,
        tigrinhos_role_id=333,
        admin_user_id=444,
    )


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


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    with create_session_factory(engine)() as s:
        yield s


async def test_collect_announces_next_24h_games(session: Session) -> None:
    provider = FakeProvider(fixtures=[_fixture(1), _fixture(2)])
    messages = await collect_sync_messages(session, provider, _settings(), now=NOW)
    assert len(messages) == 1
    assert "24h" in messages[0]
    assert "<@&333>" in messages[0]
    assert "/apostar" in messages[0]
    assert GameRepository(session).get(1) is not None
    assert GameRepository(session).get(2) is not None


async def test_collect_excludes_games_beyond_24h(session: Session) -> None:
    far = NOW + timedelta(hours=30)
    messages = await collect_sync_messages(
        session, FakeProvider(fixtures=[_fixture(1, kickoff=far)]), _settings(), now=NOW
    )
    # The game is synced into the DB but is too far out for the morning digest.
    assert messages == []
    assert GameRepository(session).get(1) is not None


async def test_collect_announces_already_known_upcoming_game(session: Session) -> None:
    settings = _settings()
    # First sync inserts the game; a later sync the same morning re-announces it because it
    # still kicks off within 24h (the digest is time-windowed, not "new games only").
    await collect_sync_messages(session, FakeProvider(fixtures=[_fixture(1)]), settings, now=NOW)
    messages = await collect_sync_messages(
        session, FakeProvider(fixtures=[_fixture(1)]), settings, now=NOW
    )
    assert len(messages) == 1
    assert "24h" in messages[0]
    assert "Brasil" in messages[0]


async def test_collect_reschedule_notice(session: Session) -> None:
    settings = _settings()
    await collect_sync_messages(session, FakeProvider(fixtures=[_fixture(1)]), settings, now=NOW)
    later = KICK + timedelta(hours=2)
    messages = await collect_sync_messages(
        session, FakeProvider(fixtures=[_fixture(1, kickoff=later)]), settings, now=NOW
    )
    assert any("remarcado" in m.lower() for m in messages)


async def test_collect_void_notice_and_voids_bets(session: Session) -> None:
    settings = _settings()
    await collect_sync_messages(session, FakeProvider(fixtures=[_fixture(1)]), settings, now=NOW)
    PlayerRepository(session).get_or_create(100, "Vitor", now=NOW)
    BetRepository(session).upsert(
        fixture_id=1, player_discord_id=100, category="WINNER", payload_json="{}", now=NOW
    )
    messages = await collect_sync_messages(
        session,
        FakeProvider(fixtures=[_fixture(1, status=GameStatus.CANCELLED)]),
        settings,
        now=NOW,
    )
    assert any("anulad" in m.lower() for m in messages)
    game = GameRepository(session).get(1)
    assert game is not None and game.status == "VOID"
    bet = BetRepository(session).get_for(1, 100, "WINNER")
    assert bet is not None and bet.points_awarded == 0


async def test_collect_no_upcoming_games_no_messages(session: Session) -> None:
    messages = await collect_sync_messages(session, FakeProvider(fixtures=[]), _settings(), now=NOW)
    assert messages == []


async def test_sync_cog_constructs_and_send_empty_is_noop(tmp_path: Path) -> None:
    from tigrinho.bot.client import TigrinhoBot

    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    bot = TigrinhoBot(_settings())
    try:
        cog = SyncCog(
            bot,
            settings=_settings(),
            session_factory=factory,
            provider_factory=lambda _session: FakeProvider(),
            clock=lambda: NOW,
        )
        await cog._send([])  # no messages -> does not touch the (offline) gateway
    finally:
        await bot.close()
