"""Tests for the Alembic migration: `upgrade head` builds a schema matching the models."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from tigrinho.db.models import Base

REPO_ROOT = Path(__file__).resolve().parent.parent


def _alembic_config(db_url: str) -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "tigrinho" / "db" / "migrations"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


@pytest.fixture
def db_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    url = f"sqlite:///{tmp_path / 'm.db'}"
    monkeypatch.setenv("TIGRINHO_DB_URL", url)
    return url


def test_upgrade_head_creates_all_tables(db_url: str) -> None:
    command.upgrade(_alembic_config(db_url), "head")
    engine = create_engine(db_url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert {"players", "games", "bets", "api_usage"} <= tables
    assert "squad_players" not in tables  # dropped by the FIRST_SCORER removal migration
    assert "alembic_version" in tables


def test_migrated_schema_matches_models(db_url: str) -> None:
    command.upgrade(_alembic_config(db_url), "head")
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            diffs = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()
    assert diffs == []


def test_upgrade_purges_first_scorer_bets_and_drops_squad(db_url: str) -> None:
    cfg = _alembic_config(db_url)
    command.upgrade(cfg, "ed421d04f4c4")  # initial schema: has squad_players + the column
    engine = create_engine(db_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO games (fixture_id, match_hash, stage, home_team_id, "
                    "home_team_name, away_team_id, away_team_name, kickoff_utc, kickoff_local, "
                    "status) VALUES (1, 'h', 'GROUP', 10, 'BRA', 20, 'ARG', "
                    "'2026-06-15 12:00:00', '2026-06-15 09:00:00', 'FINISHED')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO players (discord_id, display_name, created_at) "
                    "VALUES (100, 'Vitor', '2026-06-15 00:00:00')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO bets (fixture_id, player_discord_id, category, payload_json, "
                    "created_at, updated_at) VALUES "
                    "(1, 100, 'FIRST_SCORER', :fs, '2026-06-15 00:00:00', '2026-06-15 00:00:00'), "
                    "(1, 100, 'WINNER', :win, '2026-06-15 00:00:00', '2026-06-15 00:00:00')"
                ),
                {"fs": '{"player_id":7}', "win": '{"sel":"HOME"}'},
            )

        command.upgrade(cfg, "head")

        inspector = inspect(engine)
        assert "squad_players" not in set(inspector.get_table_names())
        assert "first_scorer_player_id" not in {c["name"] for c in inspector.get_columns("games")}
        with engine.connect() as conn:
            categories = [row[0] for row in conn.execute(text("SELECT category FROM bets"))]
        assert categories == ["WINNER"]  # FIRST_SCORER bet purged, others survive
    finally:
        engine.dispose()


def test_downgrade_base_removes_tables(db_url: str) -> None:
    cfg = _alembic_config(db_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    engine = create_engine(db_url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert "bets" not in tables
    assert "games" not in tables
