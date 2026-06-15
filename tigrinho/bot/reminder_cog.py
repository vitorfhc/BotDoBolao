"""Pre-game bet reminder (COMPLETION.md §9.4).

A DB-only reminder: shortly before each kickoff it posts one combined pt-BR message to the announce
channel pinging ``@Tigrinhos`` to place bets (which close at the opening whistle). It reads
``games.kickoff_utc`` (stored by the daily sync) and never calls the provider. The pure
:func:`select_due_reminders` / :func:`format_reminder_announcement` are kept Discord-free and
unit-tested; the :class:`ReminderCog` (``tasks.loop`` + send) is layered on top.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta, tzinfo

import discord
from discord.ext import commands, tasks
from sqlalchemy.orm import Session

from tigrinho.config import Settings
from tigrinho.db.models import Game
from tigrinho.db.repositories import GameRepository
from tigrinho.logging import get_logger

from .sync_planning import format_kickoff_pt

log = get_logger("tigrinho.bot.reminder")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def select_due_reminders(games: Sequence[Game], *, now: datetime, lead_minutes: int) -> list[Game]:
    """Games whose reminder is due this tick: not yet reminded and ``now`` is inside
    ``[kickoff - lead, kickoff)``. The upper bound (``now < kickoff``) is what makes a reminder
    "fire late" after downtime yet never fire once bets have closed. Input order is preserved
    (callers pass ``GameRepository.list_open(now)``, already ordered by kickoff)."""
    lead = timedelta(minutes=lead_minutes)
    return [
        game
        for game in games
        if game.reminder_sent_at is None and game.kickoff_utc - lead <= now < game.kickoff_utc
    ]


def format_reminder_announcement(games: Sequence[Game], *, role_mention: str, tz: tzinfo) -> str:
    """One combined pt-BR reminder for all due games, pinging the role once (§9.4). No hardcoded
    lead minutes — the actual lead varies (fire-late), so the header is time-agnostic."""
    lines = [f"⏰ **Já vai começar!** As apostas fecham no apito inicial. {role_mention}"]
    lines += [
        f"• {game.home_team_name} x {game.away_team_name} — "
        f"{format_kickoff_pt(game.kickoff_utc.astimezone(tz))}"
        for game in games
    ]
    lines.append("Corra para apostar com /apostar! 🐯")
    return "\n".join(lines)


class ReminderCog(commands.Cog):
    """Pre-game bet reminder loop (COMPLETION.md §9.4). DB-only — no provider."""

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

    async def cog_load(self) -> None:
        self.reminders.start()

    async def cog_unload(self) -> None:
        self.reminders.cancel()

    @tasks.loop(minutes=1)
    async def reminders(self) -> None:
        try:
            await self.run_reminders()
        except Exception:
            log.exception("reminders_failed")

    @reminders.before_loop
    async def _before_reminders(self) -> None:
        await self.bot.wait_until_ready()

    async def run_reminders(self) -> None:
        """Post one combined pre-game reminder (pinging the role) for every game whose lead window
        has opened and that hasn't been reminded. Resolve the channel BEFORE committing the dedup
        flag: if it's unavailable (e.g. cold cache after a restart), skip without marking so the
        next tick retries — here the message *is* the feature (§9.4)."""
        now = self._clock()
        with self.session_factory() as session:
            due = select_due_reminders(
                GameRepository(session).list_open(now),
                now=now,
                lead_minutes=self.settings.reminder_lead_minutes,
            )
            if not due:
                return
            channel = self._get_announce_channel()
            if channel is None:
                return  # cold/unavailable channel -> do not mark; retry next tick
            message = format_reminder_announcement(
                due,
                role_mention=f"<@&{self.settings.tigrinhos_role_id}>",
                tz=self.settings.tzinfo,
            )
            for game in due:
                game.reminder_sent_at = now
            session.commit()
        await channel.send(message, allowed_mentions=discord.AllowedMentions(roles=True))

    def _get_announce_channel(self) -> discord.abc.Messageable | None:
        channel = self.bot.get_channel(self.settings.announce_channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            log.warning(
                "announce_channel_unavailable", channel_id=self.settings.announce_channel_id
            )
            return None
        return channel
