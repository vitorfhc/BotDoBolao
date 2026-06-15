"""Tests for the bot skeleton: intents, /ajuda embed, role-management fail-fast check."""

from __future__ import annotations

import discord
import pytest

from tigrinho.bot.client import TigrinhoBot, build_intents, role_management_problem
from tigrinho.bot.help_cog import HELP_TITLE, HelpCog, build_help_embed
from tigrinho.config import Settings
from tigrinho.domain.text_pt import help_text


def _settings() -> Settings:
    return Settings(
        discord_token="tok",
        api_football_key="key",
        guild_id=111,
        announce_channel_id=222,
        tigrinhos_role_id=333,
        admin_user_id=444,
    )


def test_intents_request_no_privileged() -> None:
    intents = build_intents()
    assert intents.members is False
    assert intents.message_content is False
    assert intents.presences is False
    assert intents.guilds is True


def test_build_help_embed() -> None:
    embed = build_help_embed()
    assert embed.title == HELP_TITLE
    assert embed.description == help_text()
    assert embed.color == discord.Color.gold()


def test_role_management_ok() -> None:
    assert (
        role_management_problem(
            role_found=True, has_manage_roles=True, bot_top_position=5, role_position=2
        )
        is None
    )


@pytest.mark.parametrize(
    ("role_found", "has_manage_roles", "bot_top", "role_pos", "needle"),
    [
        (False, True, 5, 2, "não encontrado"),
        (True, False, 5, 2, "Manage Roles"),
        (True, True, 3, 3, "hierarquia"),  # role at/above bot
        (True, True, 3, 9, "hierarquia"),
    ],
)
def test_role_management_problems(
    role_found: bool,
    has_manage_roles: bool,
    bot_top: int,
    role_pos: int,
    needle: str,
) -> None:
    problem = role_management_problem(
        role_found=role_found,
        has_manage_roles=has_manage_roles,
        bot_top_position=bot_top,
        role_position=role_pos,
    )
    assert problem is not None
    assert needle in problem


async def test_bot_constructs_and_registers_help_command() -> None:
    bot = TigrinhoBot(_settings())
    try:
        assert bot.settings.guild_id == 111
        await bot.add_cog(HelpCog(bot))  # add_cog is offline-safe; only tree.sync needs the gateway
        assert bot.get_cog("HelpCog") is not None
        assert "ajuda" in {command.name for command in bot.tree.get_commands()}
    finally:
        await bot.close()
