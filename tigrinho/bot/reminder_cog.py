"""Pre-game bet reminder (COMPLETION.md §9.4).

A DB-only reminder: shortly before each kickoff it posts one combined pt-BR message to the announce
channel pinging ``@Tigrinhos`` to place bets (which close at the opening whistle). It reads
``games.kickoff_utc`` (stored by the daily sync) and never calls the provider. The pure
:func:`select_due_reminders` / :func:`format_reminder_announcement` are kept Discord-free and
unit-tested; the :class:`ReminderCog` (``tasks.loop`` + send) is layered on top.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, tzinfo

from tigrinho.db.models import Game

from .sync_planning import format_kickoff_pt


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
