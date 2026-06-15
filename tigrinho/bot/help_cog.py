"""`/ajuda` command — renders the pt-BR help as an ephemeral embed (COMPLETION.md §11)."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from tigrinho.domain.text_pt import help_text

HELP_TITLE = "🐯 TigrinhoDaCopa — Ajuda"


def build_help_embed() -> discord.Embed:
    """Build the /ajuda embed (pure; the description is the full pt-BR help text)."""
    return discord.Embed(title=HELP_TITLE, description=help_text(), color=discord.Color.gold())


class HelpCog(commands.Cog):
    """Provides the `/ajuda` slash command."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ajuda", description="Como funciona o bolão e todos os comandos")
    async def ajuda(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=build_help_embed(), ephemeral=True)
