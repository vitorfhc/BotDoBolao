"""Tests for pure standings computation + /placar rendering (COMPLETION.md §10)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from tigrinho.bot.board_cog import (
    Period,
    StandingInput,
    StandingRow,
    compute_standings,
    render_placar,
    week_bounds,
)
from tigrinho.domain.bets import BetCategory

UTC_TZ = ZoneInfo("UTC")
NOW = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)  # a Wednesday
EARLY = datetime(2026, 6, 1, tzinfo=UTC)
LATE = datetime(2026, 6, 10, tzinfo=UTC)
KICK = datetime(2026, 6, 16, 19, 0, tzinfo=UTC)


def _row(
    pid: int,
    *,
    points: int,
    correct: bool,
    category: BetCategory = BetCategory.WINNER,
    created_at: datetime = EARLY,
    kickoff: datetime = KICK,
    name: str | None = None,
) -> StandingInput:
    return StandingInput(
        player_discord_id=pid,
        player_name=name or f"P{pid}",
        player_created_at=created_at,
        category=category,
        is_correct=correct,
        points=points,
        kickoff_utc=kickoff,
    )


def _geral(rows: list[StandingInput]) -> list[StandingRow]:
    return compute_standings(rows, period=Period.GERAL, tz=UTC_TZ, now=NOW)


def test_orders_by_points_desc() -> None:
    standings = _geral([_row(1, points=2, correct=True), _row(2, points=5, correct=True)])
    assert [s.player_discord_id for s in standings] == [2, 1]
    assert [s.rank for s in standings] == [1, 2]


def test_tiebreak_exact_hits_beats_correct_count() -> None:
    # both 5 pts; P1 has an exact-score hit, P2 has more correct bets but no exact hit
    rows = [
        _row(1, points=5, correct=True, category=BetCategory.EXACT_SCORE),
        _row(2, points=2, correct=True, category=BetCategory.BTTS),
        _row(2, points=2, correct=True, category=BetCategory.WINNER),
        _row(2, points=1, correct=True, category=BetCategory.OVER_UNDER),  # 5 pts, 3 correct
    ]
    standings = _geral(rows)
    assert [s.player_discord_id for s in standings] == [1, 2]  # exact-hit tiebreak wins


def test_tiebreak_correct_bets() -> None:
    rows = [
        _row(1, points=2, correct=True, category=BetCategory.BTTS),
        _row(1, points=2, correct=True, category=BetCategory.WINNER),  # 4 pts, 2 correct
        _row(2, points=2, correct=True, category=BetCategory.WINNER),
        _row(2, points=1, correct=True, category=BetCategory.OVER_UNDER),
        _row(2, points=1, correct=True, category=BetCategory.OVER_UNDER),  # 4 pts, 3 correct
    ]
    standings = _geral(rows)
    assert [s.player_discord_id for s in standings] == [2, 1]  # more correct bets first


def test_tiebreak_created_at() -> None:
    rows = [
        _row(1, points=5, correct=True, category=BetCategory.EXACT_SCORE, created_at=LATE),
        _row(2, points=5, correct=True, category=BetCategory.EXACT_SCORE, created_at=EARLY),
    ]
    standings = _geral(rows)
    assert [s.player_discord_id for s in standings] == [2, 1]  # earliest created_at first


def test_week_bounds() -> None:
    start, end = week_bounds(NOW, UTC_TZ)
    assert start.weekday() == 0  # Monday
    assert end == start + timedelta(days=7)
    assert start <= NOW < end


def test_weekly_filters_to_current_week() -> None:
    start, _end = week_bounds(NOW, UTC_TZ)
    in_week = start + timedelta(days=1)
    last_week = start - timedelta(days=2)
    rows = [
        _row(1, points=5, correct=True, kickoff=in_week),
        _row(2, points=9, correct=True, kickoff=last_week),  # last week -> excluded
    ]
    weekly = compute_standings(rows, period=Period.SEMANA, tz=UTC_TZ, now=NOW)
    assert [s.player_discord_id for s in weekly] == [1]


def test_render_placar_medals_and_empty() -> None:
    assert "ainda não há" in render_placar([], period=Period.GERAL).lower()
    standings = _geral([_row(1, points=5, correct=True), _row(2, points=3, correct=True)])
    text = render_placar(standings, period=Period.GERAL)
    assert "🥇" in text
    assert "<@1>" in text


def test_render_placar_appends_caller_outside_top() -> None:
    rows = [_row(pid, points=20 - pid, correct=True) for pid in range(1, 17)]  # 16 players
    standings = _geral(rows)
    text = render_placar(standings, period=Period.GERAL, caller_id=16)
    assert "<@16>" in text
    assert "você" in text.lower()
