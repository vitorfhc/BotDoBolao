"""Tests for the cache/budget repositories (squad_players, api_usage)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import Base, SquadPlayer
from tigrinho.db.repositories import ApiUsageRepository, SquadRepository


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with factory() as s:
        yield s


def _sp(player_id: int, team_id: int, name: str) -> SquadPlayer:
    return SquadPlayer(player_id=player_id, team_id=team_id, name=name, position="FW")


# --- SquadRepository ----------------------------------------------------------


def test_squad_get_missing_returns_none(session: Session) -> None:
    assert SquadRepository(session).get(1) is None


def test_squad_replace_team_inserts_and_lists(session: Session) -> None:
    repo = SquadRepository(session)
    added = repo.replace_team(10, [_sp(1, 10, "Neymar"), _sp(2, 10, "Vini")])
    assert added == 2
    names = [p.name for p in repo.list_for_team(10)]
    assert names == ["Neymar", "Vini"]  # ordered by name
    assert repo.count() == 2


def test_squad_replace_team_refreshes_roster(session: Session) -> None:
    repo = SquadRepository(session)
    repo.replace_team(10, [_sp(1, 10, "Neymar"), _sp(2, 10, "Vini"), _sp(3, 10, "Rodrygo")])
    repo.replace_team(20, [_sp(5, 20, "Messi")])  # other team, must be untouched
    repo.replace_team(10, [_sp(2, 10, "Vini"), _sp(4, 10, "Endrick")])  # 1 & 3 dropped, 4 added
    ids_10 = {p.player_id for p in repo.list_for_team(10)}
    assert ids_10 == {2, 4}
    assert {p.player_id for p in repo.list_for_team(20)} == {5}


def test_squad_list_for_team_filters_by_team(session: Session) -> None:
    repo = SquadRepository(session)
    repo.replace_team(10, [_sp(1, 10, "A")])
    repo.replace_team(20, [_sp(2, 20, "B"), _sp(3, 20, "C")])
    assert len(repo.list_for_team(10)) == 1
    assert len(repo.list_for_team(20)) == 2


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
