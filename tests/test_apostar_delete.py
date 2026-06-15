"""Tests for the /minhas_apostas delete control (only open bets are deletable) — §8.2."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from discord import ui
from sqlalchemy.orm import Session

from tigrinho.bot.apostar_view import (
    FlowContext,
    OpenBetChoice,
    build_delete_view,
    build_open_bet_choices,
)
from tigrinho.config import Settings
from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import Base, Game
from tigrinho.db.repositories import BetRepository, PlayerRepository
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


def _ctx() -> FlowContext:
    return FlowContext(
        settings=_settings(),
        session_factory=lambda: (_ for _ in ()).throw(AssertionError("no DB in build")),
        clock=lambda: NOW,
        user_id=100,
        user_name="Vitor",
    )


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    with create_session_factory(engine)() as s:
        yield s


def _add_game(session: Session, fid: int, kickoff: datetime) -> None:
    session.add(
        Game(
            fixture_id=fid,
            match_hash="h",
            stage="GROUP",
            home_team_id=10,
            home_team_name="Brasil",
            away_team_id=20,
            away_team_name="Argentina",
            kickoff_utc=kickoff,
            kickoff_local=kickoff,
            status="SCHEDULED",
            home_goals_90=None,
            away_goals_90=None,
            advancing_team_id=None,
            first_scorer_player_id=None,
            announced_at=None,
            settled_at=None,
        )
    )
    session.flush()


def test_build_open_bet_choices_only_open(session: Session) -> None:
    _add_game(session, 1, NOW + timedelta(hours=5))  # open
    _add_game(session, 2, NOW - timedelta(hours=1))  # closed (kicked off)
    PlayerRepository(session).get_or_create(100, "Vitor", now=NOW)
    bets = BetRepository(session)
    bets.upsert(fixture_id=1, player_discord_id=100, category="WINNER", payload_json="{}", now=NOW)
    bets.upsert(fixture_id=2, player_discord_id=100, category="BTTS", payload_json="{}", now=NOW)

    choices = build_open_bet_choices(session, 100, now=NOW)
    assert len(choices) == 1
    assert choices[0].fixture_id == 1
    assert choices[0].category is BetCategory.WINNER


def test_build_delete_view_options() -> None:
    choices = [
        OpenBetChoice(fixture_id=1, category=BetCategory.WINNER, matchup="Brasil x Argentina"),
        OpenBetChoice(fixture_id=1, category=BetCategory.BTTS, matchup="Brasil x Argentina"),
    ]
    view = build_delete_view(_ctx(), choices)
    select = view.children[0]
    assert isinstance(select, ui.Select)
    assert {o.value for o in select.options} == {"1:WINNER", "1:BTTS"}
