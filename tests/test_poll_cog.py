"""Tests for PollCog wiring + scorer-name resolution (COMPLETION.md §9.2)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from discord.ext import tasks
from sqlalchemy.orm import Session

from tigrinho.bot.poll_cog import PollCog, resolve_scorer_name
from tigrinho.config import Settings
from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import Base, SquadPlayer
from tigrinho.db.repositories import SquadRepository
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


def test_resolve_scorer_name(session: Session) -> None:
    SquadRepository(session).replace_team(
        10, [SquadPlayer(player_id=7, team_id=10, name="Neymar", position="FW")]
    )
    assert resolve_scorer_name(session, 7) == "Neymar"
    assert resolve_scorer_name(session, None) is None
    assert resolve_scorer_name(session, 999) is None


async def test_poll_cog_constructs(tmp_path: Path) -> None:
    from tigrinho.bot.client import TigrinhoBot

    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    bot = TigrinhoBot(_settings())
    try:
        cog = PollCog(
            bot,
            settings=_settings(),
            session_factory=create_session_factory(engine),
            provider_factory=lambda _session: FakeProvider(),
            clock=lambda: NOW,
        )
        assert isinstance(cog.poll, tasks.Loop)
        assert cog.poll.is_running() is False  # not started until cog_load
    finally:
        await bot.close()


async def test_post_plain_sends_without_pings(tmp_path: Path) -> None:
    import discord

    from tigrinho.bot.client import TigrinhoBot

    sent: list[tuple[str, discord.AllowedMentions]] = []

    class _StubChannel(discord.abc.Messageable):
        async def _get_channel(self) -> discord.abc.MessageableChannel:
            raise NotImplementedError

        async def send(  # type: ignore[override]
            self,
            content: str,
            *,
            allowed_mentions: discord.AllowedMentions,
        ) -> None:
            sent.append((content, allowed_mentions))

    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    bot = TigrinhoBot(_settings())
    try:
        cog = PollCog(
            bot,
            settings=_settings(),
            session_factory=create_session_factory(engine),
            provider_factory=lambda _session: FakeProvider(),
            clock=lambda: NOW,
        )
        # discord.abc.Messageable check is structural enough for get_channel's return here.
        bot.get_channel = lambda _id: _StubChannel()  # type: ignore[method-assign,assignment,return-value]
        await cog._post_plain(["🟢 oi", "⚽ gol"])
    finally:
        await bot.close()

    assert [content for content, _ in sent] == ["🟢 oi", "⚽ gol"]
    assert all(am.roles is False and am.users is False and am.everyone is False for _, am in sent)
