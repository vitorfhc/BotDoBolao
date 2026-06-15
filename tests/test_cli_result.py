"""Tests for the CLI manual-result / re-settle command (COMPLETION.md §13 group 2)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session
from typer.testing import CliRunner

import tigrinho.cli as cli
from tigrinho.cli import app
from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import Base, Game
from tigrinho.db.repositories import BetRepository, GameRepository, PlayerRepository
from tigrinho.domain.bets import WinnerPayload, WinnerSelection, dump_payload

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
runner = CliRunner()


@pytest.fixture
def open_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[[], Session]]:
    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    monkeypatch.setattr(cli, "_open_session", lambda: factory())
    yield factory


def _seed(factory: Callable[[], Session]) -> None:
    with factory() as session:
        session.add(
            Game(
                fixture_id=1,
                match_hash="h",
                stage="GROUP",
                home_team_id=10,
                home_team_name="Brasil",
                away_team_id=20,
                away_team_name="Argentina",
                kickoff_utc=NOW,
                kickoff_local=NOW,
                status="LIVE",
                home_goals_90=None,
                away_goals_90=None,
                advancing_team_id=None,
                announced_at=None,
                settled_at=None,
            )
        )
        PlayerRepository(session).get_or_create(100, "Vitor", now=NOW)
        BetRepository(session).upsert(
            fixture_id=1,
            player_discord_id=100,
            category="WINNER",
            payload_json=dump_payload(WinnerPayload(WinnerSelection.HOME)),
            now=NOW,
        )
        session.commit()


def test_result_set_grades_and_updates(open_session: Callable[[], Session]) -> None:
    _seed(open_session)
    result = runner.invoke(app, ["result", "set", "1", "2", "1"])
    assert result.exit_code == 0
    assert "2x1" in result.output

    with open_session() as session:
        bet = BetRepository(session).get_for(1, 100, "WINNER")
        assert bet is not None and bet.is_correct is True and bet.points_awarded == 2
        game = GameRepository(session).get(1)
        assert game is not None
        assert game.status == "FINISHED"


def test_result_set_resettle_overwrites(open_session: Callable[[], Session]) -> None:
    _seed(open_session)
    runner.invoke(app, ["result", "set", "1", "2", "1"])  # WINNER HOME correct
    result = runner.invoke(app, ["result", "set", "1", "0", "1"])  # now AWAY won
    assert result.exit_code == 0
    with open_session() as session:
        bet = BetRepository(session).get_for(1, 100, "WINNER")
        assert bet is not None and bet.is_correct is False and bet.points_awarded == 0


def test_result_set_missing_game(open_session: Callable[[], Session]) -> None:
    result = runner.invoke(app, ["result", "set", "999", "1", "0"])
    assert result.exit_code == 1
    assert "não encontrado" in result.output.lower()
