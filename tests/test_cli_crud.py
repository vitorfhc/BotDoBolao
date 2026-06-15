"""Tests for CLI CRUD reads + db dump (COMPLETION.md §13 groups 1, 4)."""

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
from tigrinho.db.repositories import BetRepository, PlayerRepository

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
                status="SCHEDULED",
                home_goals_90=None,
                away_goals_90=None,
                advancing_team_id=None,
                announced_at=None,
                settled_at=None,
            )
        )
        PlayerRepository(session).get_or_create(100, "Vitor", now=NOW)
        BetRepository(session).upsert(
            fixture_id=1, player_discord_id=100, category="WINNER", payload_json="{}", now=NOW
        )
        session.commit()


def test_games_show(open_session: Callable[[], Session]) -> None:
    _seed(open_session)
    result = runner.invoke(app, ["games", "show", "1"])
    assert result.exit_code == 0
    assert "Brasil x Argentina" in result.output
    assert "SCHEDULED" in result.output


def test_games_show_missing(open_session: Callable[[], Session]) -> None:
    result = runner.invoke(app, ["games", "show", "999"])
    assert result.exit_code == 1


def test_bets_list_all_and_filtered(open_session: Callable[[], Session]) -> None:
    _seed(open_session)
    all_bets = runner.invoke(app, ["bets", "list"])
    assert all_bets.exit_code == 0
    assert "WINNER" in all_bets.output

    by_game = runner.invoke(app, ["bets", "list", "--game", "1"])
    assert "WINNER" in by_game.output

    by_player = runner.invoke(app, ["bets", "list", "--player", "100"])
    assert "WINNER" in by_player.output

    empty = runner.invoke(app, ["bets", "list", "--game", "999"])
    assert "nenhuma aposta" in empty.output.lower()


def test_db_dump_counts(open_session: Callable[[], Session]) -> None:
    _seed(open_session)
    result = runner.invoke(app, ["db", "dump"])
    assert result.exit_code == 0
    assert "games\t1" in result.output
    assert "players\t1" in result.output
    assert "bets\t1" in result.output


def _only_bet_id(factory: Callable[[], Session]) -> int:
    with factory() as session:
        bet = BetRepository(session).list_all()[0]
        return bet.id


def test_bets_delete_requires_confirm(open_session: Callable[[], Session]) -> None:
    _seed(open_session)
    bet_id = _only_bet_id(open_session)
    result = runner.invoke(app, ["bets", "delete", str(bet_id)])  # no --confirm
    assert result.exit_code == 1
    with open_session() as session:
        assert BetRepository(session).get(bet_id) is not None  # not deleted


def test_bets_delete_with_confirm(open_session: Callable[[], Session]) -> None:
    _seed(open_session)
    bet_id = _only_bet_id(open_session)
    result = runner.invoke(app, ["bets", "delete", str(bet_id), "--confirm"])
    assert result.exit_code == 0
    with open_session() as session:
        assert BetRepository(session).get(bet_id) is None


def test_bets_delete_missing(open_session: Callable[[], Session]) -> None:
    _seed(open_session)
    result = runner.invoke(app, ["bets", "delete", "999999", "--confirm"])
    assert result.exit_code == 1
