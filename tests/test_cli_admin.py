"""Tests for CLI budget show + board recalc (COMPLETION.md §13 groups 3-4)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session
from typer.testing import CliRunner

import tigrinho.cli as cli
from tigrinho.cli import app
from tigrinho.config import Settings
from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import Base, Game
from tigrinho.db.repositories import ApiUsageRepository, BetRepository, PlayerRepository

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
runner = CliRunner()


def _settings() -> Settings:
    return Settings(
        discord_token="tok",
        api_football_key="key",
        guild_id=111,
        announce_channel_id=222,
        tigrinhos_role_id=333,
        admin_user_id=444,
        api_daily_cap=100,  # pin so the budget-show assertions don't depend on the default
    )


@pytest.fixture
def open_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[[], Session]]:
    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    monkeypatch.setattr(cli, "_open_session", lambda: factory())
    monkeypatch.setattr(cli, "_settings", _settings)
    monkeypatch.setattr(cli, "_utcnow", lambda: NOW)
    yield factory


def test_budget_show(open_session: Callable[[], Session]) -> None:
    with open_session() as session:
        usage = ApiUsageRepository(session)
        usage.increment(NOW.date())
        usage.increment(NOW.date())  # count = 2
        session.commit()
    result = runner.invoke(app, ["budget", "show"])
    assert result.exit_code == 0
    assert "2/100" in result.output
    assert "98" in result.output  # remaining


def test_board_recalc(open_session: Callable[[], Session]) -> None:
    with open_session() as session:
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
                status="FINISHED",
                home_goals_90=2,
                away_goals_90=1,
                advancing_team_id=None,
                first_scorer_player_id=None,
                announced_at=None,
                settled_at=NOW,
            )
        )
        PlayerRepository(session).get_or_create(100, "Vitor", now=NOW)
        bet = BetRepository(session).upsert(
            fixture_id=1, player_discord_id=100, category="WINNER", payload_json="{}", now=NOW
        )
        bet.is_correct = True
        bet.points_awarded = 2
        bet.settled_at = NOW
        session.commit()
    result = runner.invoke(app, ["board", "recalc"])
    assert result.exit_code == 0
    assert "Vitor" in result.output
    assert "2" in result.output


def test_board_recalc_empty(open_session: Callable[[], Session]) -> None:
    result = runner.invoke(app, ["board", "recalc"])
    assert result.exit_code == 0
    assert "sem pontos" in result.output.lower()
