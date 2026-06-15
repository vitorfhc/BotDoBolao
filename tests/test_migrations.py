"""Tests for the Alembic migration: `upgrade head` builds a schema matching the models."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

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
    assert {"players", "games", "bets", "squad_players", "api_usage"} <= tables
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
