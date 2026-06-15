"""Pure tests for pre-game reminder selection + rendering (COMPLETION.md §9.4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tigrinho.bot.reminder_cog import select_due_reminders
from tigrinho.db.models import Game

NOW = datetime(2026, 6, 15, 18, 0, tzinfo=UTC)


def _game(fid: int, *, kickoff: datetime, reminder_sent_at: datetime | None = None) -> Game:
    return Game(
        fixture_id=fid,
        home_team_name="Brasil",
        away_team_name="Argentina",
        kickoff_utc=kickoff,
        kickoff_local=kickoff,
        reminder_sent_at=reminder_sent_at,
    )


def test_due_when_inside_lead_window() -> None:
    game = _game(1, kickoff=NOW + timedelta(minutes=30))
    assert select_due_reminders([game], now=NOW, lead_minutes=60) == [game]


def test_due_exactly_at_lead_edge() -> None:
    game = _game(1, kickoff=NOW + timedelta(minutes=60))
    assert select_due_reminders([game], now=NOW, lead_minutes=60) == [game]


def test_not_due_before_window() -> None:
    game = _game(1, kickoff=NOW + timedelta(minutes=61))
    assert select_due_reminders([game], now=NOW, lead_minutes=60) == []


def test_not_due_at_or_after_kickoff() -> None:
    game = _game(1, kickoff=NOW)
    assert select_due_reminders([game], now=NOW, lead_minutes=60) == []


def test_not_due_when_already_reminded() -> None:
    game = _game(1, kickoff=NOW + timedelta(minutes=30), reminder_sent_at=NOW)
    assert select_due_reminders([game], now=NOW, lead_minutes=60) == []


def test_fires_late_after_downtime_while_still_before_kickoff() -> None:
    # Bot was offline at kickoff-60; it's now kickoff-10, still before kickoff -> still due.
    game = _game(1, kickoff=NOW + timedelta(minutes=10))
    assert select_due_reminders([game], now=NOW, lead_minutes=60) == [game]


def test_preserves_input_order() -> None:
    g1 = _game(1, kickoff=NOW + timedelta(minutes=10))
    g2 = _game(2, kickoff=NOW + timedelta(minutes=20))
    assert select_due_reminders([g1, g2], now=NOW, lead_minutes=60) == [g1, g2]
