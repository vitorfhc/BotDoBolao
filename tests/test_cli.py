"""Tests for the admin CLI (Typer) — COMPLETION.md §13."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session
from typer.testing import CliRunner

import tigrinho.cli as cli
from tigrinho.cli import app
from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import Base, Game
from tigrinho.db.repositories import PlayerRepository

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
runner = CliRunner()


@pytest.fixture
def open_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[], Session]:
    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    monkeypatch.setattr(cli, "_open_session", lambda: factory())
    return factory


def _add_game(factory: Callable[[], Session], fid: int) -> None:
    with factory() as session:
        session.add(
            Game(
                fixture_id=fid,
                match_hash="h",
                stage="GROUP",
                home_team_id=10,
                home_team_name="Brasil",
                away_team_id=20,
                away_team_name="Argentina",
                kickoff_utc=NOW,
                kickoff_local=NOW,
                status="SCHEDULED",
                home_goals_90=None,
                away_goals_90=None,
                advancing_team_id=None,
                announced_at=None,
                settled_at=None,
            )
        )
        session.commit()


def test_games_list_empty(open_session: Callable[[], Session]) -> None:
    result = runner.invoke(app, ["games", "list"])
    assert result.exit_code == 0
    assert "nenhum jogo" in result.output.lower()


def test_games_list(open_session: Callable[[], Session]) -> None:
    _add_game(open_session, 1)
    result = runner.invoke(app, ["games", "list"])
    assert result.exit_code == 0
    assert "Brasil x Argentina" in result.output
    assert "1" in result.output


def test_players_list(open_session: Callable[[], Session]) -> None:
    with open_session() as session:
        PlayerRepository(session).get_or_create(100, "Vitor", now=NOW)
        session.commit()
    result = runner.invoke(app, ["players", "list"])
    assert result.exit_code == 0
    assert "Vitor" in result.output
    assert "100" in result.output


def test_no_args_shows_help() -> None:
    result = runner.invoke(app, [])
    # no_args_is_help -> shows usage, lists the command groups
    assert "games" in result.output
    assert "players" in result.output
