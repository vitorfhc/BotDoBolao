"""Alembic migration environment for TigrinhoDaCopa.

The database URL is resolved at runtime rather than hardcoded in ``alembic.ini``:

* ``TIGRINHO_DB_URL`` environment variable if set (used by tests and ad-hoc runs), else
* built from the validated app config's ``db_path`` (used by the container entrypoint).

``render_as_batch`` is enabled so future SQLite ALTERs work (SQLite has limited DDL).

Grounded against Alembic 1.18 docs:
https://alembic.sqlalchemy.org/en/latest/autogenerate.html
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine

from tigrinho.db.models import Base

target_metadata = Base.metadata


def _database_url() -> str:
    url = os.environ.get("TIGRINHO_DB_URL")
    if url:
        return url
    from tigrinho.config import load_settings

    return f"sqlite:///{load_settings().db_path}"


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live DB connection."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    engine = create_engine(_database_url())
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
