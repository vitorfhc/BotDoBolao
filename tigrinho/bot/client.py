"""discord.py client skeleton: config-validated bot, guild-scoped command sync, fail-fast checks.

The bot is constructed from a validated :class:`Settings` (config is validated before this point).
``setup_hook`` registers cogs and syncs the command tree to the single configured guild (instant,
unlike global sync). ``on_ready`` runs a fail-fast check that the bot can actually manage the
Tigrinhos role (Manage Roles permission + role below the bot's top role) and logs/alerts otherwise.

Grounded against discord.py 2.7 (app_commands example + setup_hook guild sync):
https://github.com/Rapptz/discord.py/blob/master/examples/app_commands/basic.py
"""

from __future__ import annotations

from collections.abc import Callable

import discord
from discord.ext import commands
from sqlalchemy.orm import Session

from tigrinho.config import Settings
from tigrinho.logging import get_logger
from tigrinho.providers.base import FootballProvider

from .bets_cog import BetsCog
from .board_cog import BoardCog
from .help_cog import HelpCog
from .poll_cog import PollCog
from .subscribe_cog import SubscribeCog
from .sync_cog import SyncCog

log = get_logger("tigrinho.bot")

SessionFactory = Callable[[], Session]
ProviderFactory = Callable[[Session], FootballProvider]


def build_intents() -> discord.Intents:
    """Gateway intents for the bot — only non-privileged ones are needed (COMPLETION.md §15)."""
    return discord.Intents.default()


def role_management_problem(
    *,
    role_found: bool,
    has_manage_roles: bool,
    bot_top_position: int,
    role_position: int,
) -> str | None:
    """Return a pt-BR problem if the bot can't manage the Tigrinhos role, else ``None``."""
    if not role_found:
        return "Cargo Tigrinhos não encontrado (verifique tigrinhos_role_id)."
    if not has_manage_roles:
        return "O bot não tem a permissão 'Manage Roles' no servidor."
    if role_position >= bot_top_position:
        return "O cargo Tigrinhos não está abaixo do cargo mais alto do bot — ajuste a hierarquia."
    return None


class TigrinhoBot(commands.Bot):
    """The TigrinhoDaCopa Discord bot (slash-command only, single guild)."""

    def __init__(
        self,
        settings: Settings,
        *,
        session_factory: SessionFactory | None = None,
        provider_factory: ProviderFactory | None = None,
    ) -> None:
        super().__init__(command_prefix=commands.when_mentioned, intents=build_intents())
        self.settings = settings
        self.session_factory = session_factory
        self.provider_factory = provider_factory

    async def setup_hook(self) -> None:
        await self._register_cogs()
        guild = discord.Object(id=self.settings.guild_id)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        log.info("commands_synced", guild_id=self.settings.guild_id)

    async def _register_cogs(self) -> None:
        """Register all cogs that have their dependencies (full set when run via create_bot)."""
        await self.add_cog(HelpCog(self))
        await self.add_cog(SubscribeCog(self, settings=self.settings))
        if self.session_factory is not None:
            await self.add_cog(
                BetsCog(self, settings=self.settings, session_factory=self.session_factory)
            )
            await self.add_cog(
                BoardCog(self, settings=self.settings, session_factory=self.session_factory)
            )
            if self.provider_factory is not None:
                await self.add_cog(
                    SyncCog(
                        self,
                        settings=self.settings,
                        session_factory=self.session_factory,
                        provider_factory=self.provider_factory,
                    )
                )
                await self.add_cog(
                    PollCog(
                        self,
                        settings=self.settings,
                        session_factory=self.session_factory,
                        provider_factory=self.provider_factory,
                    )
                )

    async def on_ready(self) -> None:
        problem = self._role_management_problem()
        if problem is not None:
            log.warning("role_management_problem", problem=problem)
        log.info("bot_ready", guild_id=self.settings.guild_id, user=str(self.user))

    def _role_management_problem(self) -> str | None:
        guild = self.get_guild(self.settings.guild_id)
        if guild is None:
            return f"O bot não está no servidor {self.settings.guild_id}."
        me = guild.me
        role = guild.get_role(self.settings.tigrinhos_role_id)
        return role_management_problem(
            role_found=role is not None,
            has_manage_roles=me.guild_permissions.manage_roles,
            bot_top_position=me.top_role.position,
            role_position=role.position if role is not None else -1,
        )
