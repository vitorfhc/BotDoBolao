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
from tigrinho.db.repositories import BetRepository, GameRepository, SquadRepository
from tigrinho.domain.bets import (
    BetCategory,
    FirstScorerPayload,
    InvalidBetPayload,
    parse_payload_json,
)
from tigrinho.domain.text_pt import render_payload
from tigrinho.providers.base import Stage

from .bets_view import MyBetLine, OpenGameLine, render_my_bets, render_open_games


def _utcnow() -> datetime:
    return datetime.now(UTC)


def build_my_bet_lines(
    session: Session, player_discord_id: int, scorer_resolver: Callable[[int], str | None]
) -> list[MyBetLine]:
    """Build a player's bet lines (resolving first-scorer names) for `/minhas_apostas`."""
    games = GameRepository(session)
    lines: list[MyBetLine] = []
    for bet in BetRepository(session).list_for_player(player_discord_id):
        game = games.get(bet.fixture_id)
        if game is None:
            continue
        category = BetCategory(bet.category)
        try:
            payload = parse_payload_json(category, bet.payload_json)
            scorer_name = (
                scorer_resolver(payload.player_id)
                if isinstance(payload, FirstScorerPayload)
                else None
            )
            value = render_payload(payload, scorer_name=scorer_name)
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
        with self.session_factory() as session:

            def resolver(player_id: int) -> str | None:
                squad_player = SquadRepository(session).get(player_id)
                return squad_player.name if squad_player is not None else None

            lines = build_my_bet_lines(session, interaction.user.id, resolver)
        await interaction.response.send_message(render_my_bets(lines), ephemeral=True)

    @app_commands.command(name="jogos", description="Ver os jogos abertos para apostar")
    async def jogos(self, interaction: discord.Interaction) -> None:
        now = self._clock()
        with self.session_factory() as session:
            lines = build_open_game_lines(session, interaction.user.id, now=now)
        await interaction.response.send_message(
            render_open_games(lines, tz=self.settings.tzinfo), ephemeral=True
        )
