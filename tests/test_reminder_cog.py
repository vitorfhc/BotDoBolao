"""Tests for ReminderCog wiring + run_reminders (COMPLETION.md §9.4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import discord
from discord.ext import tasks

from tigrinho.bot.client import TigrinhoBot
from tigrinho.bot.reminder_cog import ReminderCog
from tigrinho.config import Settings
from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import Base, Game
from tigrinho.db.repositories import GameRepository

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


class _StubChannel(discord.abc.Messageable):
    def __init__(self, sink: list[tuple[str, discord.AllowedMentions]]) -> None:
        self._sink = sink

    async def _get_channel(self) -> discord.abc.MessageableChannel:
        raise NotImplementedError

    async def send(  # type: ignore[override]
        self, content: str, *, allowed_mentions: discord.AllowedMentions
    ) -> None:
        self._sink.append((content, allowed_mentions))


def _add_game(factory: object, *, kickoff: datetime) -> None:
    with factory() as session:  # type: ignore[operator]
        session.add(
            Game(
                fixture_id=1,
                match_hash="h1",
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
                kickoff_announced_at=None,
                last_announced_home_goals=None,
                last_announced_away_goals=None,
                settled_at=None,
                reminder_sent_at=None,
            )
        )
        session.commit()


async def test_reminder_cog_constructs(tmp_path: Path) -> None:
    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    bot = TigrinhoBot(_settings())
    try:
        cog = ReminderCog(
            bot,
            settings=_settings(),
            session_factory=create_session_factory(engine),
            clock=lambda: NOW,
        )
        assert isinstance(cog.reminders, tasks.Loop)
        assert cog.reminders.is_running() is False
    finally:
        await bot.close()


async def test_run_reminders_pings_role_marks_sent_and_is_idempotent(tmp_path: Path) -> None:
    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    _add_game(factory, kickoff=NOW + timedelta(minutes=30))  # inside 60-min lead window

    sent: list[tuple[str, discord.AllowedMentions]] = []
    bot = TigrinhoBot(_settings())
    try:
        cog = ReminderCog(bot, settings=_settings(), session_factory=factory, clock=lambda: NOW)
        bot.get_channel = lambda _id: _StubChannel(sent)  # type: ignore[method-assign,assignment,return-value]
        await cog.run_reminders()
        await cog.run_reminders()  # second tick: already reminded -> nothing
    finally:
        await bot.close()

    assert len(sent) == 1
    content, am = sent[0]
    assert "<@&333>" in content and "/apostar" in content
    assert am.roles is True
    with factory() as session:
        game = GameRepository(session).get(1)
        assert game is not None and game.reminder_sent_at is not None


async def test_run_reminders_does_not_mark_when_channel_unavailable(tmp_path: Path) -> None:
    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    _add_game(factory, kickoff=NOW + timedelta(minutes=30))

    sent: list[tuple[str, discord.AllowedMentions]] = []
    bot = TigrinhoBot(_settings())
    try:
        cog = ReminderCog(bot, settings=_settings(), session_factory=factory, clock=lambda: NOW)
        bot.get_channel = lambda _id: None  # type: ignore[method-assign]
        await cog.run_reminders()  # channel cold -> skip without marking
        with factory() as session:
            game = GameRepository(session).get(1)
            assert game is not None and game.reminder_sent_at is None
        # Channel becomes available -> next tick fires.
        bot.get_channel = lambda _id: _StubChannel(sent)  # type: ignore[method-assign,assignment,return-value]
        await cog.run_reminders()
    finally:
        await bot.close()

    assert len(sent) == 1


async def test_run_reminders_skips_game_not_yet_in_window(tmp_path: Path) -> None:
    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    _add_game(factory, kickoff=NOW + timedelta(minutes=90))  # outside 60-min lead window

    sent: list[tuple[str, discord.AllowedMentions]] = []
    bot = TigrinhoBot(_settings())
    try:
        cog = ReminderCog(bot, settings=_settings(), session_factory=factory, clock=lambda: NOW)
        bot.get_channel = lambda _id: _StubChannel(sent)  # type: ignore[method-assign,assignment,return-value]
        await cog.run_reminders()
    finally:
        await bot.close()

    assert sent == []
