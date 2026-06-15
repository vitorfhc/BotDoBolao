"""`/inscrever` and `/sair` — self-service Tigrinhos notification role (COMPLETION.md §12).

The role only controls who gets @mentioned in announcements; it is NOT required to bet. Membership
lives in Discord (no DB). The pure :func:`decide_subscribe` decides the reply + whether to change
the role; the cog does the gateway role op (and reports permission/hierarchy problems in pt-BR).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import discord
from discord import app_commands
from discord.ext import commands

from tigrinho.config import Settings
from tigrinho.logging import get_logger

log = get_logger("tigrinho.bot.subscribe")


class SubscribeAction(StrEnum):
    SUBSCRIBE = "SUBSCRIBE"
    UNSUBSCRIBE = "UNSUBSCRIBE"


@dataclass(frozen=True, slots=True)
class SubscribeOutcome:
    """Whether to perform the role change, and the pt-BR ephemeral reply to send."""

    perform: bool
    message: str


def decide_subscribe(action: SubscribeAction, *, has_role: bool) -> SubscribeOutcome:
    """Decide the reply + whether the role must change, given current membership (pure)."""
    if action is SubscribeAction.SUBSCRIBE:
        if has_role:
            return SubscribeOutcome(False, "Você já está inscrito nos avisos. 🐯")
        return SubscribeOutcome(True, "Pronto! Você vai receber os avisos de novos jogos. 🔔")
    if not has_role:
        return SubscribeOutcome(False, "Você não está inscrito nos avisos.")
    return SubscribeOutcome(True, "Beleza! Você não vai mais receber os avisos.")


class SubscribeCog(commands.Cog):
    """Self-service membership of the Tigrinhos notification role."""

    def __init__(self, bot: commands.Bot, *, settings: Settings) -> None:
        self.bot = bot
        self.settings = settings

    @app_commands.command(name="inscrever", description="Receber os avisos de novos jogos")
    async def inscrever(self, interaction: discord.Interaction) -> None:
        await self._toggle(interaction, SubscribeAction.SUBSCRIBE)

    @app_commands.command(name="sair", description="Parar de receber os avisos de novos jogos")
    async def sair(self, interaction: discord.Interaction) -> None:
        await self._toggle(interaction, SubscribeAction.UNSUBSCRIBE)

    async def _toggle(self, interaction: discord.Interaction, action: SubscribeAction) -> None:
        member = interaction.user
        guild = interaction.guild
        if guild is None or not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "Use este comando dentro do servidor.", ephemeral=True
            )
            return
        role = guild.get_role(self.settings.tigrinhos_role_id)
        if role is None:
            await interaction.response.send_message(
                "O cargo de avisos não está configurado.", ephemeral=True
            )
            return

        outcome = decide_subscribe(action, has_role=role in member.roles)
        if outcome.perform:
            try:
                if action is SubscribeAction.SUBSCRIBE:
                    await member.add_roles(role, reason="/inscrever")
                else:
                    await member.remove_roles(role, reason="/sair")
            except discord.Forbidden:
                log.warning("role_change_forbidden", user=member.id, role=role.id)
                await interaction.response.send_message(
                    "Não consegui alterar seu cargo (permissão/hierarquia). Avisei o admin.",
                    ephemeral=True,
                )
                return
        await interaction.response.send_message(outcome.message, ephemeral=True)
