"""Live polling, auto-settlement & live notifications (COMPLETION.md §8.3, §9.2, §9.3).

This module holds the pure/DB core — :func:`apply_settlement` (grade a finished game's bets and
update the game), :func:`render_results_message`, and the pure kickoff/goal detectors — kept
Discord-free so they're tested against a real session. The ``tasks.loop`` ``PollCog``
(active-window polling, provider calls via the budget, posting results + live notifications,
stuck-game alerts) is layered on top.
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


@dataclass(frozen=True, slots=True)
class KickoffNotice:
    """A game that just kicked off (bets now closed)."""

    fixture_id: int
    home_team_name: str
    away_team_name: str


@dataclass(frozen=True, slots=True)
class GoalNotice:
    """A goal to announce: the resulting scoreline (no scorer — see §9.3)."""

    fixture_id: int
    home_team_name: str
    away_team_name: str
    home_goals: int
    away_goals: int


@dataclass(frozen=True, slots=True)
class GoalDelta:
    """How many new goals appeared this cycle, per side (from the live-score diff)."""

    home_new: int
    away_new: int

    @property
    def has_new(self) -> bool:
        return self.home_new > 0 or self.away_new > 0


@dataclass(frozen=True, slots=True)
class PollOutcome:
    """Everything one poll cycle produced: settlements + live-match notifications (§9.2/§9.3)."""

    settled: list[SettledGame]
    kickoffs: list[KickoffNotice]
    goals: list[GoalNotice]


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


def detect_kickoff(*, status: GameStatus, kickoff_announced_at: datetime | None) -> bool:
    """A kickoff is announceable when the game is LIVE and we haven't announced it yet."""
    return status is GameStatus.LIVE and kickoff_announced_at is None


def detect_goal_deltas(
    *,
    stored_home: int | None,
    stored_away: int | None,
    current_home: int | None,
    current_away: int | None,
) -> GoalDelta:
    """New goals per side since the last announced score. Decreases (VAR) yield zero — the caller
    resyncs the stored score down without announcing. ``None`` is treated as 0."""
    sh = 0 if stored_home is None else stored_home
    sa_ = 0 if stored_away is None else stored_away
    ch = 0 if current_home is None else current_home
    ca = 0 if current_away is None else current_away
    return GoalDelta(home_new=max(0, ch - sh), away_new=max(0, ca - sa_))


def build_goal_notices(
    *,
    fixture_id: int,
    home_team_name: str,
    away_team_name: str,
    stored_home: int | None,
    stored_away: int | None,
    current_home: int | None,
    current_away: int | None,
) -> tuple[list[GoalNotice], int, int]:
    """Turn a live-score change into one :class:`GoalNotice` per new goal, returning
    ``(notices, new_stored_home, new_stored_away)``.

    The live score is the source of truth for how many goals exist (scoreline-only — no scorer,
    since the goal timeline is not fetched, §9.3). A side whose score dropped (VAR) is silently
    resynced — no notice — while the other side is still processed. ``None`` live scores leave that
    side unchanged. Home goals are emitted before away goals, each with the running scoreline.
    """
    sh = 0 if stored_home is None else stored_home
    sa_ = 0 if stored_away is None else stored_away
    ch = sh if current_home is None else current_home
    ca = sa_ if current_away is None else current_away

    # A side whose live score dropped (VAR) resyncs without announcing; the other side still emits.
    sh = min(sh, ch)
    sa_ = min(sa_, ca)

    notices: list[GoalNotice] = []
    run_home, run_away = sh, sa_
    for _ in range(sh, ch):
        run_home += 1
        notices.append(GoalNotice(fixture_id, home_team_name, away_team_name, run_home, run_away))
    for _ in range(sa_, ca):
        run_away += 1
        notices.append(GoalNotice(fixture_id, home_team_name, away_team_name, run_home, run_away))
    return notices, ch, ca


async def collect_poll_outcome(
    session: Session, provider: FootballProvider, settings: Settings, *, now: datetime
) -> PollOutcome:
    """Run one poll pass over every pollable game and return its outcome (COMPLETION.md §9.2/§9.3).

    One date-windowed call fetches current status + live score for all games. For each game we:
    - settle it if now FINISHED (fetching the authoritative final result once);
    - else, while LIVE, announce the kickoff once and any new goals (detected for free from the
      live-score diff; scoreline-only, no extra provider call).

    Self-healing settlement is unchanged. Dedup state is persisted on the game row, so this is
    idempotent across restarts. May raise ``BudgetExceeded`` (the cog turns it into a skip). No
    commit — the caller commits.
    """
    games = GameRepository(session)
    pollable = games.list_active(now, settings.settle_grace_hours)
    if not pollable:
        return PollOutcome(settled=[], kickoffs=[], goals=[])
    results = {
        result.fixture_id: result
        for result in await provider.get_recent_results(settings.settle_grace_hours)
    }
    settled: list[SettledGame] = []
    kickoffs: list[KickoffNotice] = []
    goal_notices: list[GoalNotice] = []
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
            continue
        if result.status is GameStatus.LIVE:
            if detect_kickoff(status=result.status, kickoff_announced_at=game.kickoff_announced_at):
                game.kickoff_announced_at = now
                kickoffs.append(
                    KickoffNotice(game.fixture_id, game.home_team_name, game.away_team_name)
                )
            # Skip goal detection when the live score is entirely unknown (pre-score minutes or a
            # brief API hiccup): the persisted counters stay put, which keeps the poll idempotent.
            if result.home_goals is not None or result.away_goals is not None:
                notices, new_home, new_away = build_goal_notices(
                    fixture_id=game.fixture_id,
                    home_team_name=game.home_team_name,
                    away_team_name=game.away_team_name,
                    stored_home=game.last_announced_home_goals,
                    stored_away=game.last_announced_away_goals,
                    current_home=result.home_goals,
                    current_away=result.away_goals,
                )
                game.last_announced_home_goals = new_home
                game.last_announced_away_goals = new_away
                goal_notices.extend(notices)
    session.flush()
    return PollOutcome(settled=settled, kickoffs=kickoffs, goals=goal_notices)


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


def render_kickoff_message(home_team_name: str, away_team_name: str) -> str:
    """pt-BR kickoff message (bets are now closed)."""
    return (
        f"🟢 **Bola rolando!** {home_team_name} x {away_team_name} — "
        "as apostas estão encerradas. 🐯"
    )


def render_goal_message(notice: GoalNotice) -> str:
    """pt-BR goal message: just the new scoreline (no scorer — §9.3)."""
    return (
        f"⚽ **Gol!** {notice.home_team_name} {notice.home_goals}x{notice.away_goals} "
        f"{notice.away_team_name}"
    )


class PollCog(commands.Cog):
    """Live polling, auto-settlement, results + live notifications, and stuck-game alerts (§9.2)."""

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
        """One poll cycle: settle finished games, announce kickoffs and goals for live games
        (throttling rechecks of overdue ones), and alert the admin about games that outlived the
        settlement grace (§9.2/§9.3)."""
        now = self._clock()
        with self.session_factory() as session:
            games = GameRepository(session)
            pollable = games.list_active(now, self.settings.settle_grace_hours)
            outcome = PollOutcome(settled=[], kickoffs=[], goals=[])
            if should_poll(
                pollable_kickoffs=[game.kickoff_utc for game in pollable],
                now=now,
                last_poll=self._last_poll,
                match_window_hours=self.settings.match_window_hours,
                stuck_recheck_minutes=self.settings.stuck_recheck_minutes,
            ):
                self._last_poll = now
                provider = self.provider_factory(session)
                outcome = await collect_poll_outcome(session, provider, self.settings, now=now)
            live_messages = [
                render_kickoff_message(kickoff.home_team_name, kickoff.away_team_name)
                for kickoff in outcome.kickoffs
            ] + [render_goal_message(goal) for goal in outcome.goals]
            stuck = [
                (game.fixture_id, f"{game.home_team_name} x {game.away_team_name}")
                for game in games.list_stuck(now, self.settings.settle_grace_hours)
            ]
            session.commit()
        await self._post_plain(live_messages)
        await self._post_results(outcome.settled)
        await self._alert_stuck(stuck)

    def _get_announce_channel(self) -> discord.abc.Messageable | None:
        channel = self.bot.get_channel(self.settings.announce_channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            log.warning(
                "announce_channel_unavailable", channel_id=self.settings.announce_channel_id
            )
            return None
        return channel

    async def _post_plain(self, messages: list[str]) -> None:
        """Post kickoff/goal messages to the announce channel with no pings."""
        if not messages:
            return
        channel = self._get_announce_channel()
        if channel is None:
            return
        for message in messages:
            await channel.send(message, allowed_mentions=discord.AllowedMentions.none())

    async def _post_results(self, results: list[SettledGame]) -> None:
        if not results:
            return
        channel = self._get_announce_channel()
        if channel is None:
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
