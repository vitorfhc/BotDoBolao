"""Tests for the cache/budget repositories (api_usage)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import Base
from tigrinho.db.repositories import ApiUsageRepository


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with factory() as s:
        yield s


# --- ApiUsageRepository -------------------------------------------------------


def test_api_usage_count_zero_when_absent(session: Session) -> None:
    assert ApiUsageRepository(session).get_count(date(2026, 6, 15)) == 0


def test_api_usage_increment_creates_then_increments(session: Session) -> None:
    repo = ApiUsageRepository(session)
    d = date(2026, 6, 15)
    assert repo.increment(d) == 1
    assert repo.increment(d) == 2
    assert repo.get_count(d) == 2


def test_api_usage_days_are_independent(session: Session) -> None:
    repo = ApiUsageRepository(session)
    repo.increment(date(2026, 6, 15))
    repo.increment(date(2026, 6, 15))
    repo.increment(date(2026, 6, 16))
    assert repo.get_count(date(2026, 6, 15)) == 2
    assert repo.get_count(date(2026, 6, 16)) == 1
