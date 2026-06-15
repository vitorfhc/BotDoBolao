"""SQLAlchemy engine + session factory for the local SQLite database (COMPLETION.md §3).

Synchronous SQLite (local queries are sub-ms); the same engine/session code is shared by the
bot and the CLI. Foreign-key enforcement is enabled per connection (SQLite defaults it off).
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry


def _sqlite_url(db_path: str) -> str:
    if db_path in {":memory:", ""}:
        return "sqlite://"
    return f"sqlite:///{db_path}"


def create_db_engine(db_path: str, *, echo: bool = False) -> Engine:
    """Create a synchronous SQLite :class:`Engine` with foreign-key enforcement on."""
    engine = create_engine(_sqlite_url(db_path), echo=echo)

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(
        dbapi_connection: DBAPIConnection, _record: ConnectionPoolEntry
    ) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build a session factory; sessions keep attributes accessible after commit."""
    return sessionmaker(bind=engine, expire_on_commit=False)
