"""Tests for the Tigrinhos notification role cog (/inscrever, /sair) — COMPLETION.md §12."""

from __future__ import annotations

from pathlib import Path

from tigrinho.bot.subscribe_cog import (
    SubscribeAction,
    SubscribeCog,
    decide_subscribe,
)
from tigrinho.config import Settings


def _settings() -> Settings:
    return Settings(
        discord_token="tok",
        api_football_key="key",
        guild_id=111,
        announce_channel_id=222,
        tigrinhos_role_id=333,
        admin_user_id=444,
    )


def test_subscribe_when_not_subscribed_performs_and_confirms() -> None:
    outcome = decide_subscribe(SubscribeAction.SUBSCRIBE, has_role=False)
    assert outcome.perform is True
    assert "avisos" in outcome.message.lower()


def test_subscribe_when_already_subscribed_is_noop() -> None:
    outcome = decide_subscribe(SubscribeAction.SUBSCRIBE, has_role=True)
    assert outcome.perform is False
    assert "já está inscrito" in outcome.message.lower()


def test_unsubscribe_when_subscribed_performs() -> None:
    outcome = decide_subscribe(SubscribeAction.UNSUBSCRIBE, has_role=True)
    assert outcome.perform is True


def test_unsubscribe_when_not_subscribed_is_noop() -> None:
    outcome = decide_subscribe(SubscribeAction.UNSUBSCRIBE, has_role=False)
    assert outcome.perform is False
    assert "não está inscrito" in outcome.message.lower()


async def test_cog_registers_subscribe_commands(tmp_path: Path) -> None:
    from tigrinho.bot.client import TigrinhoBot

    bot = TigrinhoBot(_settings())
    try:
        await bot.add_cog(SubscribeCog(bot, settings=_settings()))
        names = {command.name for command in bot.tree.get_commands()}
        assert {"inscrever", "sair"} <= names
    finally:
        await bot.close()
