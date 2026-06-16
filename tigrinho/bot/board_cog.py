"""Scoreboard computation + /placar rendering (COMPLETION.md §10).

The standings are derived purely from settled-bet rows (so the CLI can rebuild them). This module
holds that pure computation + the pt-BR rendering; the ``BoardCog`` (`/placar`) is layered on top.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta, tzinfo
from enum import StrEnum
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.orm import Session

from tigrinho.config import Settings
from tigrinho.db.models import Bet, Game, Player
from tigrinho.domain.bets import BetCategory


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Period(StrEnum):
    """Scoreboard period: whole tournament or the current Mon→Sun week."""

    GERAL = "geral"
    SEMANA = "semana"


@dataclass(frozen=True, slots=True)
class StandingInput:
    """One settled bet, as needed to compute standings (rebuildable from the DB)."""

    player_discord_id: int
    player_name: str
    player_created_at: datetime
    category: BetCategory
    is_correct: bool
    points: int
    kickoff_utc: datetime


@dataclass(frozen=True, slots=True)
class StandingRow:
    """A ranked player on the scoreboard."""

    rank: int
    player_discord_id: int
    player_name: str
    total_points: int
    exact_hits: int
    correct_bets: int


@dataclass
class _Acc:
    name: str
    created_at: datetime
    points: int = 0
    exact_hits: int = 0
    correct_bets: int = 0


def week_bounds(now: datetime, tz: tzinfo) -> tuple[datetime, datetime]:
    """The current Mon→Sun week in ``tz`` as ``[start, end)`` tz-aware datetimes (resets Monday)."""
    local_now = now.astimezone(tz)
    monday = local_now.date() - timedelta(days=local_now.weekday())
    start = datetime.combine(monday, time.min, tzinfo=tz)
    return start, start + timedelta(days=7)


def compute_standings(
    rows: list[StandingInput], *, period: Period, tz: tzinfo, now: datetime
) -> list[StandingRow]:
    """Aggregate settled bets into ranked standings (tie-breaks per COMPLETION.md §10)."""
    if period is Period.SEMANA:
        start, end = week_bounds(now, tz)
        rows = [row for row in rows if start <= row.kickoff_utc.astimezone(tz) < end]

    accumulators: dict[int, _Acc] = {}
    for row in rows:
        acc = accumulators.get(row.player_discord_id)
        if acc is None:
            acc = _Acc(name=row.player_name, created_at=row.player_created_at)
            accumulators[row.player_discord_id] = acc
        acc.points += row.points
        if row.is_correct:
            acc.correct_bets += 1
            if row.category is BetCategory.EXACT_SCORE:
                acc.exact_hits += 1

    ordered = sorted(
        accumulators.items(),
        # tie-breaks: total points, exact-score hits, correct bets (all desc), then earliest signup
        key=lambda item: (
            -item[1].points,
            -item[1].exact_hits,
            -item[1].correct_bets,
            item[1].created_at,
        ),
    )
    return [
        StandingRow(
            rank=index + 1,
            player_discord_id=player_id,
            player_name=acc.name,
            total_points=acc.points,
            exact_hits=acc.exact_hits,
            correct_bets=acc.correct_bets,
        )
        for index, (player_id, acc) in enumerate(ordered)
    ]


_MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
_TOP_N = 15


def render_placar(
    standings: list[StandingRow], *, period: Period, caller_id: int | None = None
) -> str:
    """Render the top ~15 (medals for top 3) and the caller's own line if they're outside it."""
    title = "🏆 **Placar geral**" if period is Period.GERAL else "🏆 **Placar da semana**"
    if not standings:
        return f"{title}\nAinda não há pontos. Boa sorte! 🐯"

    top = standings[:_TOP_N]
    lines = [title]
    for row in top:
        prefix = _MEDALS.get(row.rank, f"{row.rank}.")
        lines.append(f"{prefix} <@{row.player_discord_id}> — {row.total_points} pt(s)")

    if caller_id is not None and all(row.player_discord_id != caller_id for row in top):
        own = next((row for row in standings if row.player_discord_id == caller_id), None)
        if own is not None:
            lines.append("…")
            own_line = f"{own.rank}. <@{own.player_discord_id}> — {own.total_points} pt(s) (você)"
            lines.append(own_line)
    return "\n".join(lines)


def build_standing_inputs(session: Session) -> list[StandingInput]:
    """Load every settled bet (joined to its player + game) as a :class:`StandingInput` (§10)."""
    stmt = (
        select(Bet, Player, Game)
        .join(Player, Bet.player_discord_id == Player.discord_id)
        .join(Game, Bet.fixture_id == Game.fixture_id)
        .where(Bet.settled_at.is_not(None))
    )
    inputs: list[StandingInput] = []
    for bet, player, game in session.execute(stmt).tuples():
        inputs.append(
            StandingInput(
                player_discord_id=bet.player_discord_id,
                player_name=player.display_name,
                player_created_at=player.created_at,
                category=BetCategory(bet.category),
                is_correct=bool(bet.is_correct),
                points=bet.points_awarded or 0,
                kickoff_utc=game.kickoff_utc,
            )
        )
    return inputs


class BoardCog(commands.Cog):
    """The `/placar` scoreboard command."""

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

    @app_commands.command(name="placar", description="Ver o ranking (geral ou da semana)")
    @app_commands.describe(periodo="Período do ranking: geral (padrão) ou semana")
    async def placar(
        self, interaction: discord.Interaction, periodo: Literal["geral", "semana"] = "geral"
    ) -> None:
        period = Period(periodo)
        now = self._clock()
        with self.session_factory() as session:
            rows = build_standing_inputs(session)
        standings = compute_standings(rows, period=period, tz=self.settings.tzinfo, now=now)
        # /placar is social — post publicly (not ephemeral). Render <@id> links for
        # readability, but suppress pings so the whole leaderboard isn't notified.
        await interaction.response.send_message(
            render_placar(standings, period=period, caller_id=interaction.user.id),
            allowed_mentions=discord.AllowedMentions.none(),
        )
