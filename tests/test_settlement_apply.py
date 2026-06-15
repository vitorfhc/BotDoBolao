"""Tests for poll-cog settlement application + results message (COMPLETION.md §8.3)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from tigrinho.bot.poll_cog import (
    PlayerResult,
    SettledGame,
    apply_settlement,
    render_results_message,
)
from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import Base, Game
from tigrinho.db.repositories import BetRepository, PlayerRepository
from tigrinho.domain.bets import (
    BetCategory,
    ExactScorePayload,
    OverUnderPayload,
    OverUnderSelection,
    WinnerPayload,
    WinnerSelection,
    dump_payload,
)
from tigrinho.providers.base import GameStatus, GoalEvent, MatchResult, Stage

NOW = datetime(2026, 6, 15, 18, 0, tzinfo=UTC)


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    with create_session_factory(engine)() as s:
        yield s


def _seed_game_and_bets(session: Session) -> None:
    session.add(
        Game(
            fixture_id=1,
            match_hash="h",
            stage="GROUP",
            home_team_id=10,
            home_team_name="Brasil",
            away_team_id=20,
            away_team_name="Argentina",
            kickoff_utc=NOW - timedelta(hours=2),
            kickoff_local=NOW - timedelta(hours=2),
            status="LIVE",
            home_goals_90=None,
            away_goals_90=None,
            advancing_team_id=None,
            first_scorer_player_id=None,
            announced_at=None,
            settled_at=None,
        )
    )
    PlayerRepository(session).get_or_create(100, "Vitor", now=NOW)
    PlayerRepository(session).get_or_create(200, "Ana", now=NOW)
    bets = BetRepository(session)
    bets.upsert(
        fixture_id=1,
        player_discord_id=100,
        category="WINNER",
        payload_json=dump_payload(WinnerPayload(WinnerSelection.HOME)),
        now=NOW,
    )
    bets.upsert(
        fixture_id=1,
        player_discord_id=100,
        category="EXACT_SCORE",
        payload_json=dump_payload(ExactScorePayload(2, 1)),
        now=NOW,
    )
    bets.upsert(
        fixture_id=1,
        player_discord_id=200,
        category="OVER_UNDER",
        payload_json=dump_payload(OverUnderPayload(OverUnderSelection.UNDER)),
        now=NOW,
    )


def _result() -> MatchResult:
    return MatchResult(
        fixture_id=1,
        status=GameStatus.FINISHED,
        stage=Stage.GROUP,
        home_goals_90=2,
        away_goals_90=1,
        goals=(GoalEvent(10, 10, 7, "Neymar", is_own_goal=False, is_penalty=False),),
        advancing_team_id=None,
    )


def test_apply_settlement_grades_and_updates_game(session: Session) -> None:
    _seed_game_and_bets(session)
    settled = apply_settlement(session, _result(), now=NOW)
    assert settled is not None

    bets = BetRepository(session)
    winner = bets.get_for(1, 100, "WINNER")
    exact = bets.get_for(1, 100, "EXACT_SCORE")
    under = bets.get_for(1, 200, "OVER_UNDER")
    assert winner is not None and winner.is_correct is True and winner.points_awarded == 2
    assert exact is not None and exact.points_awarded == 5
    assert under is not None and under.is_correct is False and under.points_awarded == 0

    from tigrinho.db.repositories import GameRepository

    game = GameRepository(session).get(1)
    assert game is not None
    assert game.status == "FINISHED"
    assert game.home_goals_90 == 2
    assert game.settled_at == NOW

    totals = {p.player_discord_id: p.total_points for p in settled.players}
    assert totals == {100: 7, 200: 0}


def test_apply_settlement_idempotent(session: Session) -> None:
    _seed_game_and_bets(session)
    first = apply_settlement(session, _result(), now=NOW)
    second = apply_settlement(session, _result(), now=NOW + timedelta(minutes=5))
    assert first is not None and second is not None
    assert {p.player_discord_id: p.total_points for p in first.players} == {
        p.player_discord_id: p.total_points for p in second.players
    }


def test_apply_settlement_missing_game(session: Session) -> None:
    assert apply_settlement(session, _result(), now=NOW) is None


def test_render_results_message() -> None:
    settled = SettledGame(
        fixture_id=1,
        home_team_name="Brasil",
        away_team_name="Argentina",
        home_goals_90=2,
        away_goals_90=1,
        players=[
            PlayerResult(
                player_discord_id=100,
                total_points=7,
                lines=[(BetCategory.WINNER, True, 2), (BetCategory.EXACT_SCORE, True, 5)],
            ),
            PlayerResult(
                player_discord_id=200, total_points=0, lines=[(BetCategory.OVER_UNDER, False, 0)]
            ),
        ],
    )
    text = render_results_message(settled)
    assert "Brasil 2x1 Argentina" in text
    assert "<@100>" in text and "<@200>" in text  # all participants mentioned
    assert "7" in text


def test_render_results_message_no_players() -> None:
    settled = SettledGame(
        fixture_id=1,
        home_team_name="Brasil",
        away_team_name="Argentina",
        home_goals_90=0,
        away_goals_90=0,
        players=[],
    )
    text = render_results_message(settled)
    assert "0x0" in text
    assert "Pontos" not in text  # no points section when nobody bet
