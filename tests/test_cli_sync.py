"""Tests for CLI force-sync + squad seeding (COMPLETION.md §13 group 3)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session
from typer.testing import CliRunner

import tigrinho.cli as cli
from tigrinho.cli import app
from tigrinho.config import Settings
from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import Base
from tigrinho.db.repositories import GameRepository, SquadRepository
from tigrinho.providers.base import Fixture, GameStatus, SquadPlayer, Stage
from tigrinho.providers.fake import FakeProvider

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
        provider_mode="fake",
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


def test_squads_seed(open_session: Callable[[], Session], monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeProvider(
        squads={10: [SquadPlayer(player_id=7, team_id=10, name="Neymar", position="FW")]}
    )
    monkeypatch.setattr(cli, "_build_provider", lambda settings, session: fake)
    result = runner.invoke(app, ["squads", "seed", "10"])
    assert result.exit_code == 0
    assert "1" in result.output
    with open_session() as session:
        squad = SquadRepository(session).list_for_team(10)
        assert [p.player_id for p in squad] == [7]
        assert squad[0].name == "Neymar"


def test_sync_run(open_session: Callable[[], Session], monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = Fixture(
        fixture_id=1,
        stage=Stage.GROUP,
        home_team_id=10,
        home_team_name="Brasil",
        away_team_id=20,
        away_team_name="Argentina",
        kickoff_utc=NOW + timedelta(hours=5),
        status=GameStatus.SCHEDULED,
    )
    fake = FakeProvider(fixtures=[fixture])
    monkeypatch.setattr(cli, "_build_provider", lambda settings, session: fake)
    result = runner.invoke(app, ["sync", "run"])
    assert result.exit_code == 0
    with open_session() as session:
        assert GameRepository(session).get(1) is not None
