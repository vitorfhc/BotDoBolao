"""Tests for the composition root: create_bot + setup_hook wiring all cogs (COMPLETION.md §15)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from tigrinho.bootstrap import create_bot
from tigrinho.bot.client import TigrinhoBot
from tigrinho.config import Settings
from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import Base
from tigrinho.providers.base import FootballProvider
from tigrinho.providers.fake import FakeProvider

ALL_COGS = {"HelpCog", "SubscribeCog", "BetsCog", "BoardCog", "SyncCog", "PollCog"}
ALL_COMMANDS = {"ajuda", "inscrever", "sair", "minhas_apostas", "jogos", "apostar", "placar"}


def _settings(*, db_path: str = "/tmp/x.db", mode: str = "fake") -> Settings:
    return Settings(
        discord_token="tok",
        api_football_key="key",
        guild_id=111,
        announce_channel_id=222,
        tigrinhos_role_id=333,
        admin_user_id=444,
        provider_mode=mode,
        db_path=db_path,
    )


async def test_register_cogs_wires_everything(tmp_path: Path) -> None:
    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)

    def provider_factory(_session: Session) -> FootballProvider:
        return FakeProvider()

    bot = TigrinhoBot(
        _settings(),
        session_factory=create_session_factory(engine),
        provider_factory=provider_factory,
    )
    try:
        await bot._register_cogs()
        assert set(bot.cogs) >= ALL_COGS
        assert {command.name for command in bot.tree.get_commands()} >= ALL_COMMANDS
    finally:
        for name in list(bot.cogs):
            await bot.remove_cog(name)  # cancels the cogs' tasks.loops
        await bot.close()


async def test_create_bot_builds_runtime(tmp_path: Path) -> None:
    bot = create_bot(_settings(db_path=str(tmp_path / "t.db"), mode="fake"))
    try:
        assert isinstance(bot, TigrinhoBot)
        assert bot.session_factory is not None
        assert bot.provider_factory is not None
    finally:
        await bot.close()
