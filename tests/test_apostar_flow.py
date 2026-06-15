"""Tests for the /apostar component flow builders (COMPLETION.md §8.2)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from discord import ui

from tigrinho.bot.apostar_view import (
    APOSTAR_CATEGORIES,
    FlowContext,
    GameChoice,
    build_apostar_view,
    build_category_view,
    build_value_view,
    games_to_choices,
)
from tigrinho.config import Settings
from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import Base, Game
from tigrinho.domain.bets import BetCategory
from tigrinho.providers.base import Stage

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
KICK = datetime(2026, 6, 15, 19, 0, tzinfo=UTC)


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
def ctx(tmp_path: Path) -> Iterator[FlowContext]:
    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    yield FlowContext(
        settings=_settings(),
        session_factory=create_session_factory(engine),
        clock=lambda: NOW,
        user_id=100,
        user_name="Vitor",
    )


def _game(fid: int, *, stage: str = "GROUP") -> Game:
    return Game(
        fixture_id=fid,
        match_hash="h",
        stage=stage,
        home_team_id=10,
        home_team_name="Brasil",
        away_team_id=20,
        away_team_name="Argentina",
        kickoff_utc=KICK,
        kickoff_local=KICK,
        status="SCHEDULED",
        home_goals_90=None,
        away_goals_90=None,
        advancing_team_id=None,
        first_scorer_player_id=None,
        announced_at=None,
        settled_at=None,
    )


def _first_select(view: ui.View) -> ui.Select[ui.View]:
    item = view.children[0]
    assert isinstance(item, ui.Select)
    return item


def test_games_to_choices() -> None:
    choices = games_to_choices([_game(1), _game(2)], _settings().tzinfo)
    assert [c.fixture_id for c in choices] == [1, 2]
    assert "Brasil x Argentina" in choices[0].label
    assert choices[0].stage is Stage.GROUP


def test_apostar_view_lists_games(ctx: FlowContext) -> None:
    choices = [
        GameChoice(fixture_id=1, label="A x B", stage=Stage.GROUP, matchup="A x B"),
        GameChoice(fixture_id=2, label="C x D", stage=Stage.KNOCKOUT, matchup="C x D"),
    ]
    select = _first_select(build_apostar_view(ctx, choices))
    assert {o.value for o in select.options} == {"1", "2"}


def test_category_view_offers_implemented_categories(ctx: FlowContext) -> None:
    select = _first_select(
        build_category_view(ctx, fixture_id=1, stage=Stage.GROUP, matchup="A x B")
    )
    assert len(select.options) == len(APOSTAR_CATEGORIES)
    assert {o.value for o in select.options} == {c.value for c in APOSTAR_CATEGORIES}


def test_value_view_winner_knockout_hides_draw(ctx: FlowContext) -> None:
    select = _first_select(
        build_value_view(
            ctx, fixture_id=1, matchup="A x B", category=BetCategory.WINNER, stage=Stage.KNOCKOUT
        )
    )
    values = {o.value for o in select.options}
    assert values == {"HOME", "AWAY"}  # no DRAW in knockout


def test_value_view_winner_group_includes_draw(ctx: FlowContext) -> None:
    select = _first_select(
        build_value_view(
            ctx, fixture_id=1, matchup="A x B", category=BetCategory.WINNER, stage=Stage.GROUP
        )
    )
    assert {o.value for o in select.options} == {"HOME", "DRAW", "AWAY"}


def test_value_view_btts_and_over_under(ctx: FlowContext) -> None:
    btts = _first_select(
        build_value_view(
            ctx, fixture_id=1, matchup="A x B", category=BetCategory.BTTS, stage=Stage.GROUP
        )
    )
    assert len(btts.options) == 4
    over_under = _first_select(
        build_value_view(
            ctx, fixture_id=1, matchup="A x B", category=BetCategory.OVER_UNDER, stage=Stage.GROUP
        )
    )
    assert {o.value for o in over_under.options} == {"OVER", "UNDER"}


async def test_apostar_command_registered(tmp_path: Path) -> None:
    from tigrinho.bot.bets_cog import BetsCog
    from tigrinho.bot.client import TigrinhoBot

    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    bot = TigrinhoBot(_settings())
    try:
        await bot.add_cog(
            BetsCog(bot, settings=_settings(), session_factory=create_session_factory(engine))
        )
        assert "apostar" in {c.name for c in bot.tree.get_commands()}
    finally:
        await bot.close()
