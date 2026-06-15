"""Betting commands: `/minhas_apostas` and `/jogos` (COMPLETION.md §8.2).

The DB→view builders are kept separate from the cog so they can be tested against a real session;
the cog itself is a thin gateway layer (fetch → render → ephemeral reply). The `/apostar` component
flow is layered on top of these + ``bets_logic.place_bet``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy.orm import Session

from tigrinho.config import Settings
from tigrinho.db.repositories import BetRepository, GameRepository
from tigrinho.domain.bets import (
    BetCategory,
    InvalidBetPayload,
    parse_payload_json,
)
from tigrinho.domain.text_pt import render_payload
from tigrinho.providers.base import Stage

from .apostar_view import (
    FlowContext,
    build_apostar_view,
    build_delete_view,
    build_open_bet_choices,
    games_to_choices,
)
from .bets_view import MyBetLine, OpenGameLine, render_my_bets, render_open_games


def _utcnow() -> datetime:
    return datetime.now(UTC)


def build_my_bet_lines(session: Session, player_discord_id: int) -> list[MyBetLine]:
    """Build a player's bet lines for `/minhas_apostas`."""
    games = GameRepository(session)
    lines: list[MyBetLine] = []
    for bet in BetRepository(session).list_for_player(player_discord_id):
        game = games.get(bet.fixture_id)
        if game is None:
            continue
        category = BetCategory(bet.category)
        try:
            payload = parse_payload_json(category, bet.payload_json)
            value = render_payload(
                payload,
                home_name=game.home_team_name,
                away_name=game.away_team_name,
            )
        except InvalidBetPayload:
            value = "(inválido)"
        lines.append(
            MyBetLine(
                matchup=f"{game.home_team_name} x {game.away_team_name}",
                category=category,
                value=value,
                settled=bet.settled_at is not None,
                is_correct=bet.is_correct,
                points=bet.points_awarded,
            )
        )
    return lines


def build_open_game_lines(
    session: Session, player_discord_id: int, *, now: datetime
) -> list[OpenGameLine]:
    """Build open-game lines with the caller's already-bet categories for `/jogos`."""
    bets_by_fixture: dict[int, set[BetCategory]] = {}
    for bet in BetRepository(session).list_for_player(player_discord_id):
        bets_by_fixture.setdefault(bet.fixture_id, set()).add(BetCategory(bet.category))
    lines: list[OpenGameLine] = []
    for game in GameRepository(session).list_open(now):
        lines.append(
            OpenGameLine(
                matchup=f"{game.home_team_name} x {game.away_team_name}",
                kickoff_utc=game.kickoff_utc,
                stage=Stage(game.stage),
                bet_categories=frozenset(bets_by_fixture.get(game.fixture_id, set())),
            )
        )
    return lines


class BetsCog(commands.Cog):
    """Read-only betting views; the `/apostar` flow is added on top."""

    def __init__(
        self,
        bot: commands.Bot,
        *,
        settings: Settings,
        session_factory: Callable[[], Session],
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.bot = bot
        self.settings = settings
        self.session_factory = session_factory
        self._clock = clock

    @app_commands.command(
        name="minhas_apostas", description="Ver seus palpites (abertos e apurados)"
    )
    async def minhas_apostas(self, interaction: discord.Interaction) -> None:
        now = self._clock()
        with self.session_factory() as session:
            lines = build_my_bet_lines(session, interaction.user.id)
            open_choices = build_open_bet_choices(session, interaction.user.id, now=now)
        text = render_my_bets(lines)
        if not open_choices:
            await interaction.response.send_message(text, ephemeral=True)
            return
        ctx = FlowContext(
            settings=self.settings,
            session_factory=self.session_factory,
            clock=self._clock,
            user_id=interaction.user.id,
            user_name=interaction.user.display_name,
        )
        await interaction.response.send_message(
            text, view=build_delete_view(ctx, open_choices), ephemeral=True
        )

    @app_commands.command(name="apostar", description="Fazer ou editar um palpite")
    async def apostar(self, interaction: discord.Interaction) -> None:
        now = self._clock()
        with self.session_factory() as session:
            choices = games_to_choices(GameRepository(session).list_open(now), self.settings.tzinfo)
        if not choices:
            await interaction.response.send_message(
                "Nenhum jogo aberto para apostar agora. ⏳", ephemeral=True
            )
            return
        ctx = FlowContext(
            settings=self.settings,
            session_factory=self.session_factory,
            clock=self._clock,
            user_id=interaction.user.id,
            user_name=interaction.user.display_name,
        )
        await interaction.response.send_message(
            "Escolha um jogo para apostar:", view=build_apostar_view(ctx, choices), ephemeral=True
        )

    @app_commands.command(name="jogos", description="Ver os jogos abertos para apostar")
    async def jogos(self, interaction: discord.Interaction) -> None:
        now = self._clock()
        with self.session_factory() as session:
            lines = build_open_game_lines(session, interaction.user.id, now=now)
        await interaction.response.send_message(
            render_open_games(lines, tz=self.settings.tzinfo), ephemeral=True
        )
