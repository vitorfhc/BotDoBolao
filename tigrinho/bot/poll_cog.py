"""Live polling & auto-settlement (COMPLETION.md §8.3, §9.2).

This module holds the pure/DB core — :func:`apply_settlement` (grade a finished game's bets and
update the game) and :func:`render_results_message` — kept Discord-free so they're tested against a
real session. The ``tasks.loop`` ``PollCog`` (active-window polling, provider calls via the budget,
posting results, stuck-game alerts) is layered on top.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import discord
from discord.ext import commands, tasks
from sqlalchemy.orm import Session

from tigrinho.config import Settings
from tigrinho.db.repositories import BetRepository, GameRepository
from tigrinho.domain.bets import BetCategory
from tigrinho.domain.settlement import BetInput, match_facts_from_result, settle_game
from tigrinho.domain.text_pt import CATEGORY_LABELS_PT
from tigrinho.logging import get_logger
from tigrinho.providers.base import FootballProvider, GameStatus, MatchResult
from tigrinho.providers.budget import BudgetExceeded

from .alerts import dm_admin

log = get_logger("tigrinho.bot.poll")


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class PlayerResult:
    """One player's outcome for a settled game."""

    player_discord_id: int
    total_points: int
    lines: list[tuple[BetCategory, bool, int]]  # (category, is_correct, points)


@dataclass(frozen=True, slots=True)
class SettledGame:
    """Everything needed to post a game's results message."""

    fixture_id: int
    home_team_name: str
    away_team_name: str
    home_goals_90: int
    away_goals_90: int
    players: list[PlayerResult]


def apply_settlement(session: Session, result: MatchResult, *, now: datetime) -> SettledGame | None:
    """Grade every bet for a finished game and update the game (idempotent). Returns ``None`` if
    the game is unknown. Raises ``ValueError`` if the 90' score is missing (caller treats as stuck).
    """
    game = GameRepository(session).get(result.fixture_id)
    if game is None:
        return None
    facts = match_facts_from_result(
        result, home_team_id=game.home_team_id, away_team_id=game.away_team_id
    )
    bet_rows = BetRepository(session).list_for_game(result.fixture_id)
    inputs = [
        BetInput(bet_id=row.id, category=BetCategory(row.category), payload_json=row.payload_json)
        for row in bet_rows
    ]
    outcomes = {outcome.bet_id: outcome for outcome in settle_game(facts, inputs)}

    by_player: dict[int, list[tuple[BetCategory, bool, int]]] = {}
    for row in bet_rows:
        outcome = outcomes[row.id]
        row.is_correct = outcome.is_correct
        row.points_awarded = outcome.points_awarded
        row.settled_at = now
        by_player.setdefault(row.player_discord_id, []).append(
            (BetCategory(row.category), outcome.is_correct, outcome.points_awarded)
        )

    game.status = GameStatus.FINISHED.value
    game.home_goals_90 = facts.home_goals_90
    game.away_goals_90 = facts.away_goals_90
    game.advancing_team_id = result.advancing_team_id
    game.settled_at = now
    session.flush()

    players = [
        PlayerResult(
            player_discord_id=player_id,
            total_points=sum(points for _, _, points in lines),
            lines=lines,
        )
        for player_id, lines in by_player.items()
    ]
    return SettledGame(
        fixture_id=result.fixture_id,
        home_team_name=game.home_team_name,
        away_team_name=game.away_team_name,
        home_goals_90=facts.home_goals_90,
        away_goals_90=facts.away_goals_90,
        players=players,
    )


def should_poll(
    *,
    pollable_kickoffs: list[datetime],
    now: datetime,
    last_poll: datetime | None,
    match_window_hours: int,
    stuck_recheck_minutes: int,
) -> bool:
    """Decide whether to hit the provider this cycle (COMPLETION.md §9.2).

    Poll every cycle while any pollable game is within the match window (fast/live cadence). Once
    only overdue games remain — past the match window but still within ``settle_grace_hours`` —
    throttle to ``stuck_recheck_minutes`` between provider calls: a stuck game doesn't change
    minute-to-minute, so frequent rechecks would just waste budget.
    """
    if not pollable_kickoffs:
        return False
    fast_cutoff = now - timedelta(hours=match_window_hours)
    if any(kickoff >= fast_cutoff for kickoff in pollable_kickoffs):
        return True  # a game is inside its live window — poll now
    if last_poll is None:
        return True  # overdue games we haven't rechecked yet
    return now - last_poll >= timedelta(minutes=stuck_recheck_minutes)


async def collect_settlements(
    session: Session, provider: FootballProvider, settings: Settings, *, now: datetime
) -> list[SettledGame]:
    """Settle every unsettled game (kicked off within ``settle_grace_hours``) that is now finished.

    Self-healing (COMPLETION.md §9.2): a game keeps being polled until it settles or outlives the
    grace, so late finishes (extra time, penalties) and API status lag recover with no manual step.
    Returns immediately with no provider call if nothing is pollable. One date-windowed call fetches
    current statuses for all games at once; only games reported finished cost an extra per-game
    request (the goal timeline). May raise ``BudgetExceeded`` (the cog turns it into a skip). No
    commit — the caller commits.
    """
    games = GameRepository(session)
    pollable = games.list_active(now, settings.settle_grace_hours)
    if not pollable:
        return []
    results = {
        result.fixture_id: result
        for result in await provider.get_recent_results(settings.settle_grace_hours)
    }
    settled: list[SettledGame] = []
    for game in pollable:
        result = results.get(game.fixture_id)
        if result is None:
            continue
        game.status = result.status.value
        if result.status is GameStatus.FINISHED:
            full_result = await provider.get_match_result(game.fixture_id)
            outcome = apply_settlement(session, full_result, now=now)
            if outcome is not None:
                settled.append(outcome)
    session.flush()
    return settled


def render_results_message(settled: SettledGame) -> str:
    """Render the pt-BR results message: 90' score and each player's points (§8.3)."""
    lines = [
        f"🏁 **{settled.home_team_name} {settled.home_goals_90}x{settled.away_goals_90} "
        f"{settled.away_team_name}** — resultado final (90')"
    ]
    if settled.players:
        lines.append("🏆 **Pontos:**")
        for player in sorted(settled.players, key=lambda p: (-p.total_points, p.player_discord_id)):
            breakdown = ", ".join(
                f"{CATEGORY_LABELS_PT[category]} {'✅' if correct else '❌'}"
                for category, correct, _points in player.lines
            )
            lines.append(
                f"<@{player.player_discord_id}>: {player.total_points} pt(s) — {breakdown}"
            )
    return "\n".join(lines)


class PollCog(commands.Cog):
    """Live polling, auto-settlement, results messages, and stuck-game alerts (§9.2)."""

    def __init__(
        self,
        bot: commands.Bot,
        *,
        settings: Settings,
        session_factory: Callable[[], Session],
        provider_factory: Callable[[Session], FootballProvider],
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.bot = bot
        self.settings = settings
        self.session_factory = session_factory
        self.provider_factory = provider_factory
        self._clock = clock
        self._alerted_stuck: set[int] = set()
        self._last_poll: datetime | None = None

    async def cog_load(self) -> None:
        self.poll.change_interval(minutes=self.settings.poll_interval_minutes)
        self.poll.start()

    async def cog_unload(self) -> None:
        self.poll.cancel()

    @tasks.loop(minutes=10)
    async def poll(self) -> None:
        try:
            await self.run_poll()
        except BudgetExceeded:
            log.warning("poll_skipped_budget_exceeded")
        except Exception:
            log.exception("poll_failed")

    @poll.before_loop
    async def _before_poll(self) -> None:
        await self.bot.wait_until_ready()

    async def run_poll(self) -> None:
        """One poll cycle: settle finished games (throttling rechecks of overdue ones), post
        results, and alert the admin about games that outlived the settlement grace (§9.2)."""
        now = self._clock()
        with self.session_factory() as session:
            games = GameRepository(session)
            pollable = games.list_active(now, self.settings.settle_grace_hours)
            results: list[SettledGame] = []
            if should_poll(
                pollable_kickoffs=[game.kickoff_utc for game in pollable],
                now=now,
                last_poll=self._last_poll,
                match_window_hours=self.settings.match_window_hours,
                stuck_recheck_minutes=self.settings.stuck_recheck_minutes,
            ):
                self._last_poll = now
                provider = self.provider_factory(session)
                results = await collect_settlements(session, provider, self.settings, now=now)
            stuck = [
                (game.fixture_id, f"{game.home_team_name} x {game.away_team_name}")
                for game in games.list_stuck(now, self.settings.settle_grace_hours)
            ]
            session.commit()
        await self._post_results(results)
        await self._alert_stuck(stuck)

    async def _post_results(self, results: list[SettledGame]) -> None:
        if not results:
            return
        channel = self.bot.get_channel(self.settings.announce_channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            log.warning(
                "announce_channel_unavailable", channel_id=self.settings.announce_channel_id
            )
            return
        allowed = discord.AllowedMentions(users=True)
        for settled in results:
            await channel.send(render_results_message(settled), allowed_mentions=allowed)

    async def _alert_stuck(self, stuck: list[tuple[int, str]]) -> None:
        for fixture_id, matchup in stuck:
            if fixture_id in self._alerted_stuck:
                continue
            self._alerted_stuck.add(fixture_id)
            await dm_admin(
                self.bot,
                self.settings.admin_user_id,
                f"⚠️ Jogo {matchup} (#{fixture_id}) segue sem apuração "
                f"{self.settings.settle_grace_hours}h após o início. Resolva manualmente pela CLI.",
            )
