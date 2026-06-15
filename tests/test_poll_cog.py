"""Tests for PollCog wiring (COMPLETION.md §9.2)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from discord.ext import tasks

from tigrinho.bot.poll_cog import PollCog
from tigrinho.config import Settings
from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import Base
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
