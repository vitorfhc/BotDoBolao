"""Pure daily-sync planning + pt-BR announcement text (COMPLETION.md §9.1).

No I/O, no discord — the cog fetches fixtures + reads existing games, calls :func:`plan_sync` to
classify them into new / rescheduled / voided, applies the DB changes, and sends the text built
here. Keeping this pure makes the new/reschedule/void rules exhaustively testable.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Protocol

from tigrinho.providers.base import Fixture, GameStatus


class Matchup(Protocol):
    """Minimal structural view needed to render a matchup line (satisfied by ``Fixture`` and the
    ``Game`` ORM row), so the announcement text stays pure and works off either source.

    Members are read-only properties so the frozen ``Fixture`` dataclass satisfies the protocol.
    """

    @property
    def home_team_name(self) -> str: ...

    @property
    def away_team_name(self) -> str: ...

    @property
    def kickoff_utc(self) -> datetime: ...


# pt-BR weekday abbreviations, Monday=0 .. Sunday=6.
_WEEKDAYS_PT = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")


@dataclass(frozen=True, slots=True)
class ExistingGame:
    """Minimal view of a stored game needed for sync planning."""

    fixture_id: int
    kickoff_utc: datetime
    status: GameStatus


@dataclass(frozen=True, slots=True)
class SyncPlan:
    """What a sync should do: insert+announce ``new``, update+re-announce ``rescheduled``, void."""

    new: list[Fixture]
    rescheduled: list[Fixture]
    voided: list[Fixture]


def compute_match_hash(kickoff_utc: datetime, home_team_id: int, away_team_id: int) -> str:
    """Human-readable dedup label, NOT identity: ``sha256(kickoff_iso|home_id|away_id)`` (§6)."""
    raw = f"{kickoff_utc.isoformat()}|{home_team_id}|{away_team_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_placeholder_fixture(fixture: Fixture) -> bool:
    """True if a fixture's teams aren't really decided yet (skip it — §9.1)."""
    return (
        fixture.home_team_id <= 0
        or fixture.away_team_id <= 0
        or not fixture.home_team_name.strip()
        or not fixture.away_team_name.strip()
    )


def plan_sync(fixtures: Sequence[Fixture], existing: Mapping[int, ExistingGame]) -> SyncPlan:
    """Classify provider ``fixtures`` against ``existing`` games into a :class:`SyncPlan`."""
    new: list[Fixture] = []
    rescheduled: list[Fixture] = []
    voided: list[Fixture] = []
    for fixture in fixtures:
        if is_placeholder_fixture(fixture):
            continue
        if fixture.status in (GameStatus.POSTPONED, GameStatus.CANCELLED):
            seen = existing.get(fixture.fixture_id)
            if seen is not None and seen.status is not GameStatus.VOID:
                voided.append(fixture)
            continue
        seen = existing.get(fixture.fixture_id)
        if seen is None:
            if fixture.status is GameStatus.SCHEDULED:
                new.append(fixture)
        elif fixture.status is GameStatus.SCHEDULED and seen.kickoff_utc != fixture.kickoff_utc:
            rescheduled.append(fixture)
    return SyncPlan(new=new, rescheduled=rescheduled, voided=voided)


def format_kickoff_pt(kickoff_local: datetime) -> str:
    """Format a (localized) kickoff as ``Sáb 16/06 16:00``."""
    weekday = _WEEKDAYS_PT[kickoff_local.weekday()]
    return f"{weekday} {kickoff_local:%d/%m %H:%M}"


def _matchup_line(matchup: Matchup, tz: tzinfo) -> str:
    when = format_kickoff_pt(matchup.kickoff_utc.astimezone(tz))
    return f"• {matchup.home_team_name} x {matchup.away_team_name} — {when}"


def format_daily_games_announcement(
    games: Sequence[Matchup], *, role_mention: str, tz: tzinfo
) -> str:
    """Build the morning digest of games kicking off in the next 24h, pinging the role (§9.1).

    Unlike a per-sync "new games" notice, this is time-windowed: every morning it lists the games
    open for bets that kick off within the next 24h, regardless of which sync first added them.
    """
    lines = [f"🐯 Jogos das próximas 24h! Bora apostar? {role_mention}"]
    lines += [_matchup_line(game, tz) for game in games]
    lines.append("Use /apostar para palpitar (fecha no apito inicial).")
    return "\n".join(lines)


def format_reschedule_notice(fixture: Fixture, *, tz: tzinfo) -> str:
    """Concise note that a known game moved; existing bets stay valid (§9.1)."""
    when = format_kickoff_pt(fixture.kickoff_utc.astimezone(tz))
    return (
        f"🔄 Jogo remarcado: {fixture.home_team_name} x {fixture.away_team_name} — "
        f"agora {when}. Suas apostas seguem valendo."
    )


def format_void_notice(fixture: Fixture) -> str:
    """Concise note that a game was postponed/cancelled and its bets were voided (§9.1)."""
    return (
        f"⚠️ Jogo cancelado/adiado: {fixture.home_team_name} x {fixture.away_team_name}. "
        f"As apostas foram anuladas (sem pontos)."
    )
