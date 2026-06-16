"""Tests for the pure sync-planning logic + pt-BR announcement text (COMPLETION.md §9.1)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from tigrinho.bot.sync_planning import (
    ExistingGame,
    compute_match_hash,
    format_daily_games_announcement,
    format_kickoff_pt,
    format_reschedule_notice,
    format_void_notice,
    plan_sync,
)
from tigrinho.providers.base import Fixture, GameStatus, Stage

SP = ZoneInfo("America/Sao_Paulo")
KICK = datetime(2026, 6, 15, 19, 0, tzinfo=UTC)  # 16:00 in São Paulo (UTC-3)


def _fixture(
    fid: int,
    *,
    kickoff: datetime = KICK,
    status: GameStatus = GameStatus.SCHEDULED,
    home: int = 10,
    away: int = 20,
    home_name: str = "Brasil",
    away_name: str = "Argentina",
) -> Fixture:
    return Fixture(
        fixture_id=fid,
        stage=Stage.GROUP,
        home_team_id=home,
        home_team_name=home_name,
        away_team_id=away,
        away_team_name=away_name,
        kickoff_utc=kickoff,
        status=status,
    )


def _existing(
    fid: int, *, kickoff: datetime = KICK, status: GameStatus = GameStatus.SCHEDULED
) -> dict[int, ExistingGame]:
    return {fid: ExistingGame(fixture_id=fid, kickoff_utc=kickoff, status=status)}


# --- match hash ---


def test_match_hash_is_deterministic_and_sensitive() -> None:
    h1 = compute_match_hash(KICK, 10, 20)
    assert h1 == compute_match_hash(KICK, 10, 20)
    assert len(h1) == 64  # sha256 hexdigest
    assert h1 != compute_match_hash(KICK, 20, 10)  # team order matters
    assert h1 != compute_match_hash(KICK.replace(hour=20), 10, 20)  # kickoff matters


# --- planning ---


def test_new_scheduled_fixture_is_announced() -> None:
    plan = plan_sync([_fixture(1)], {})
    assert [f.fixture_id for f in plan.new] == [1]
    assert plan.rescheduled == []
    assert plan.voided == []


def test_unchanged_fixture_produces_no_action() -> None:
    plan = plan_sync([_fixture(1)], _existing(1))
    assert plan.new == []
    assert plan.rescheduled == []
    assert plan.voided == []


def test_changed_kickoff_is_a_reschedule() -> None:
    later = KICK.replace(hour=21)
    plan = plan_sync([_fixture(1, kickoff=later)], _existing(1, kickoff=KICK))
    assert [f.fixture_id for f in plan.rescheduled] == [1]
    assert plan.new == []


def test_postponed_and_cancelled_existing_are_voided() -> None:
    fixtures = [
        _fixture(1, status=GameStatus.POSTPONED),
        _fixture(2, status=GameStatus.CANCELLED),
    ]
    existing = {
        1: ExistingGame(1, KICK, GameStatus.SCHEDULED),
        2: ExistingGame(2, KICK, GameStatus.SCHEDULED),
    }
    plan = plan_sync(fixtures, existing)
    assert {f.fixture_id for f in plan.voided} == {1, 2}


def test_already_void_game_is_not_revoided() -> None:
    plan = plan_sync(
        [_fixture(1, status=GameStatus.CANCELLED)], _existing(1, status=GameStatus.VOID)
    )
    assert plan.voided == []


def test_unseen_cancelled_is_ignored() -> None:
    plan = plan_sync([_fixture(1, status=GameStatus.CANCELLED)], {})
    assert plan.new == [] and plan.voided == []


def test_placeholder_fixtures_are_skipped() -> None:
    placeholders = [
        _fixture(1, home=0),  # undetermined team id
        _fixture(2, away_name="  "),  # blank name
    ]
    assert plan_sync(placeholders, {}).new == []


def test_finished_unseen_fixture_is_not_announced() -> None:
    assert plan_sync([_fixture(1, status=GameStatus.FINISHED)], {}).new == []


# --- pt-BR text ---


def test_format_kickoff_pt_shape() -> None:
    text = format_kickoff_pt(KICK.astimezone(SP))
    assert re.fullmatch(r"(Seg|Ter|Qua|Qui|Sex|Sáb|Dom) \d{2}/\d{2} \d{2}:\d{2}", text)
    assert "16:00" in text  # localized to São Paulo


def test_daily_games_announcement() -> None:
    text = format_daily_games_announcement(
        [_fixture(1), _fixture(2, home_name="França", away_name="Alemanha")],
        role_mention="<@&333>",
        tz=SP,
    )
    assert "<@&333>" in text
    assert "24h" in text  # the morning digest is framed as the next-24h games
    assert "Brasil" in text and "Argentina" in text
    assert "França" in text and "Alemanha" in text
    assert "/apostar" in text
    assert "16:00" in text


def test_reschedule_notice() -> None:
    text = format_reschedule_notice(_fixture(1, kickoff=KICK.replace(hour=22)), tz=SP)
    assert "Brasil" in text and "Argentina" in text
    assert "19:00" in text  # 22:00 UTC -> 19:00 SP
    assert "valendo" in text.lower()


def test_void_notice() -> None:
    text = format_void_notice(_fixture(1, status=GameStatus.CANCELLED))
    assert "Brasil" in text and "Argentina" in text
    assert "anulad" in text.lower()
