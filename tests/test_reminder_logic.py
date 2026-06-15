"""Pure tests for pre-game reminder selection + rendering (COMPLETION.md §9.4)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from tigrinho.bot.reminder_cog import format_reminder_announcement, select_due_reminders
from tigrinho.db.models import Game

NOW = datetime(2026, 6, 15, 18, 0, tzinfo=UTC)
SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def _game(fid: int, *, kickoff: datetime, reminder_sent_at: datetime | None = None) -> Game:
    return Game(
        fixture_id=fid,
        match_hash=f"h{fid}",
        stage="GROUP",
        home_team_id=10,
        home_team_name="Brasil",
        away_team_id=20,
        away_team_name="Argentina",
        kickoff_utc=kickoff,
        kickoff_local=kickoff,
        status="SCHEDULED",
        home_goals_90=None,
        away_goals_90=None,
        advancing_team_id=None,
        announced_at=None,
        kickoff_announced_at=None,
        last_announced_home_goals=None,
        last_announced_away_goals=None,
        settled_at=None,
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


def test_format_single_game_has_ping_and_kickoff_and_apostar() -> None:
    game = _game(1, kickoff=datetime(2026, 6, 16, 19, 0, tzinfo=UTC))
    msg = format_reminder_announcement([game], role_mention="<@&333>", tz=SAO_PAULO)
    assert "<@&333>" in msg
    assert "Brasil x Argentina" in msg
    assert "/apostar" in msg
    # 19:00 UTC -> 16:00 America/Sao_Paulo, with the weekday prefix format_kickoff_pt produces
    assert re.search(r"(Seg|Ter|Qua|Qui|Sex|Sáb|Dom) 16/06 16:00", msg) is not None


def test_format_multiple_games_lists_each_with_one_header() -> None:
    g1 = _game(1, kickoff=datetime(2026, 6, 16, 19, 0, tzinfo=UTC))
    g2 = _game(2, kickoff=datetime(2026, 6, 16, 22, 0, tzinfo=UTC))
    msg = format_reminder_announcement([g1, g2], role_mention="<@&333>", tz=SAO_PAULO)
    assert msg.count("<@&333>") == 1  # one ping for the whole batch
    assert msg.count("Brasil x Argentina") == 2
