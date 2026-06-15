"""Tests for the FIRST_SCORER step of /apostar: squad loading + paginated select (§8.2)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from discord import ui
from sqlalchemy.orm import Session

from tigrinho.bot.apostar_view import (
    APOSTAR_CATEGORIES,
    FlowContext,
    ScorerChoice,
    build_squad_view,
    load_scorer_choices,
)
from tigrinho.config import Settings
from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import Base, SquadPlayer
from tigrinho.db.repositories import SquadRepository
from tigrinho.domain.bets import BetCategory

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


def _settings() -> Settings:
    return Settings(
        discord_token="tok",
        api_football_key="key",
        guild_id=111,
        announce_channel_id=222,
        tigrinhos_role_id=333,
        admin_user_id=444,
    )


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    with create_session_factory(engine)() as s:
        yield s


def _ctx() -> FlowContext:
    return FlowContext(
        settings=_settings(),
        session_factory=lambda: (_ for _ in ()).throw(AssertionError("no DB in build")),
        clock=lambda: NOW,
        user_id=100,
        user_name="Vitor",
    )


def _selects(view: ui.View) -> list[ui.Select[ui.View]]:
    return [c for c in view.children if isinstance(c, ui.Select)]


def _buttons(view: ui.View) -> list[ui.Button[ui.View]]:
    return [c for c in view.children if isinstance(c, ui.Button)]


def test_first_scorer_is_offered() -> None:
    assert BetCategory.FIRST_SCORER in APOSTAR_CATEGORIES


def test_load_scorer_choices_combines_both_teams(session: Session) -> None:
    repo = SquadRepository(session)
    repo.replace_team(10, [SquadPlayer(player_id=7, team_id=10, name="Neymar", position="FW")])
    repo.replace_team(20, [SquadPlayer(player_id=8, team_id=20, name="Messi", position="FW")])
    choices = load_scorer_choices(session, 10, 20)
    assert {c.player_id for c in choices} == {7, 8}
    assert {c.name for c in choices} == {"Neymar", "Messi"}


def test_build_squad_view_paginates() -> None:
    scorers = [ScorerChoice(player_id=i, name=f"P{i}") for i in range(30)]
    page0 = build_squad_view(_ctx(), fixture_id=1, matchup="A x B", scorers=scorers, page=0)
    assert len(_selects(page0)[0].options) == 25
    prev0, next0 = _buttons(page0)
    assert prev0.disabled is True  # first page
    assert next0.disabled is False

    page1 = build_squad_view(_ctx(), fixture_id=1, matchup="A x B", scorers=scorers, page=1)
    assert len(_selects(page1)[0].options) == 5
    prev1, next1 = _buttons(page1)
    assert prev1.disabled is False
    assert next1.disabled is True  # last page


def test_build_squad_view_single_page_has_no_buttons() -> None:
    view = build_squad_view(
        _ctx(), fixture_id=1, matchup="A x B", scorers=[ScorerChoice(1, "X")], page=0
    )
    assert len(_buttons(view)) == 0
    assert {o.value for o in _selects(view)[0].options} == {"1"}
