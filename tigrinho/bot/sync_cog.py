"""Daily fixtures sync (COMPLETION.md §9.1).

This module currently holds :func:`apply_plan` — the DB-mutation half of a sync, kept free of any
Discord dependency so it can be tested against a real SQLite session. The :class:`SyncCog`
(``tasks.loop`` scheduling, provider fetch via the budget, and announcement sending) is layered on
top of this.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, tzinfo

import discord
from discord.ext import commands, tasks
from sqlalchemy.orm import Session

from tigrinho.config import Settings
from tigrinho.db.models import Game
from tigrinho.db.repositories import BetRepository, GameRepository
from tigrinho.logging import get_logger
from tigrinho.providers.base import Fixture, FootballProvider, GameStatus
from tigrinho.providers.budget import BudgetExceeded

from .sync_planning import (
    ExistingGame,
    SyncPlan,
    compute_match_hash,
    format_daily_games_announcement,
    format_reschedule_notice,
    format_void_notice,
    plan_sync,
)

SYNC_WINDOW_HOURS = 48
# How far ahead the daily morning announcement looks (COMPLETION.md §9.1).
DAILY_ANNOUNCE_HOURS = 24
log = get_logger("tigrinho.bot.sync")


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class AppliedSync:
    """Counts of what a sync applied (for logging)."""

    new: int
    rescheduled: int
    voided: int


def _game_from_fixture(fixture: Fixture, tz: tzinfo) -> Game:
    return Game(
        fixture_id=fixture.fixture_id,
        match_hash=compute_match_hash(
            fixture.kickoff_utc, fixture.home_team_id, fixture.away_team_id
        ),
        stage=fixture.stage.value,
        home_team_id=fixture.home_team_id,
        home_team_name=fixture.home_team_name,
        away_team_id=fixture.away_team_id,
        away_team_name=fixture.away_team_name,
        kickoff_utc=fixture.kickoff_utc,
        kickoff_local=fixture.kickoff_utc.astimezone(tz),
        status=fixture.status.value,
        home_goals_90=None,
        away_goals_90=None,
        advancing_team_id=None,
        announced_at=None,
        settled_at=None,
    )


def apply_plan(session: Session, plan: SyncPlan, *, now: datetime, tz: tzinfo) -> AppliedSync:
    """Apply a :class:`SyncPlan` to the DB (insert new, update rescheduled, void cancelled).

    Voiding a game sets it ``VOID`` + ``settled_at`` (so it drops out of open/active queries) and
    voids its bets (0 points, no longer gradable). The caller commits and sends the announcements.
    """
    games = GameRepository(session)
    bets = BetRepository(session)

    for fixture in plan.new:
        games.add(_game_from_fixture(fixture, tz))

    for fixture in plan.rescheduled:
        game = games.get(fixture.fixture_id)
        if game is not None:
            game.kickoff_utc = fixture.kickoff_utc
            game.kickoff_local = fixture.kickoff_utc.astimezone(tz)
            game.match_hash = compute_match_hash(
                fixture.kickoff_utc, fixture.home_team_id, fixture.away_team_id
            )
            game.status = GameStatus.SCHEDULED.value
            game.reminder_sent_at = None

    for fixture in plan.voided:
        game = games.get(fixture.fixture_id)
        if game is not None:
            game.status = GameStatus.VOID.value
            game.settled_at = now
            for bet in bets.list_for_game(fixture.fixture_id):
                bet.is_correct = None
                bet.points_awarded = 0
                bet.settled_at = now

    session.flush()
    return AppliedSync(
        new=len(plan.new), rescheduled=len(plan.rescheduled), voided=len(plan.voided)
    )


async def collect_sync_messages(
    session: Session, provider: FootballProvider, settings: Settings, *, now: datetime
) -> list[str]:
    """Run one sync: fetch fixtures, plan, apply to the DB, and return messages to announce.

    The morning announcement is the **next-24h games digest** (built from the DB after applying the
    plan, so it reflects every open game in the window — not just the ones this sync added).
    Reschedule and void notices about already-tracked games are still posted as concise messages.

    No Discord I/O and no commit — the caller (the cog) commits and sends. May raise
    ``BudgetExceeded`` from the provider, which the cog turns into a skip.
    """
    games = GameRepository(session)
    existing = {
        game.fixture_id: ExistingGame(
            fixture_id=game.fixture_id,
            kickoff_utc=game.kickoff_utc,
            status=GameStatus(game.status),
        )
        for game in games.list_all()
    }
    fixtures = await provider.get_fixtures(SYNC_WINDOW_HOURS)
    plan = plan_sync(fixtures, existing)
    apply_plan(session, plan, now=now, tz=settings.tzinfo)

    role_mention = f"<@&{settings.tigrinhos_role_id}>"
    messages: list[str] = []
    upcoming = games.list_upcoming(now, DAILY_ANNOUNCE_HOURS)
    if upcoming:
        messages.append(
            format_daily_games_announcement(upcoming, role_mention=role_mention, tz=settings.tzinfo)
        )
    messages += [
        format_reschedule_notice(fixture, tz=settings.tzinfo) for fixture in plan.rescheduled
    ]
    messages += [format_void_notice(fixture) for fixture in plan.voided]
    return messages


class SyncCog(commands.Cog):
    """Daily fixtures sync loop + announcements (COMPLETION.md §9.1)."""

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
        local_time = settings.sync_time_of_day
        self._sync_time = time(
            hour=local_time.hour, minute=local_time.minute, tzinfo=settings.tzinfo
        )

    async def cog_load(self) -> None:
        self.daily_sync.change_interval(time=self._sync_time)
        self.daily_sync.start()

    async def cog_unload(self) -> None:
        self.daily_sync.cancel()

    @tasks.loop(time=time(0, 0))
    async def daily_sync(self) -> None:
        try:
            await self.run_sync()
        except BudgetExceeded:
            log.warning("daily_sync_skipped_budget_exceeded")
        except Exception:
            log.exception("daily_sync_failed")

    @daily_sync.before_loop
    async def _before_daily_sync(self) -> None:
        await self.bot.wait_until_ready()

    async def run_sync(self) -> None:
        """Open a session, sync, commit, then announce (used by the loop and CLI force-sync)."""
        now = self._clock()
        with self.session_factory() as session:
            provider = self.provider_factory(session)
            messages = await collect_sync_messages(session, provider, self.settings, now=now)
            session.commit()
        await self._send(messages)

    async def _send(self, messages: list[str]) -> None:
        if not messages:
            return
        channel = self.bot.get_channel(self.settings.announce_channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            log.warning(
                "announce_channel_unavailable", channel_id=self.settings.announce_channel_id
            )
            return
        allowed = discord.AllowedMentions(roles=True)
        for message in messages:
            await channel.send(message, allowed_mentions=allowed)
