"""Tests for build_standing_inputs (DB) + BoardCog /placar registration (COMPLETION.md §10)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from tigrinho.bot.board_cog import BoardCog, build_standing_inputs
from tigrinho.config import Settings
from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import Base, Game
from tigrinho.db.repositories import BetRepository, PlayerRepository
from tigrinho.domain.bets import BetCategory

NOW = datetime(2026, 6, 15, 18, 0, tzinfo=UTC)


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


def _add_game(session: Session, fid: int, *, settled: datetime | None) -> None:
    session.add(
        Game(
            fixture_id=fid,
            match_hash="h",
            stage="GROUP",
            home_team_id=10,
            home_team_name="Brasil",
            away_team_id=20,
            away_team_name="Argentina",
            kickoff_utc=NOW - timedelta(hours=3),
            kickoff_local=NOW - timedelta(hours=3),
            status="FINISHED" if settled else "SCHEDULED",
            home_goals_90=None,
            away_goals_90=None,
            advancing_team_id=None,
            first_scorer_player_id=None,
            announced_at=None,
            settled_at=settled,
        )
    )
    session.flush()


def test_build_standing_inputs_only_settled(session: Session) -> None:
    _add_game(session, 1, settled=NOW)
    _add_game(session, 2, settled=None)
    PlayerRepository(session).get_or_create(100, "Vitor", now=NOW)
    bets = BetRepository(session)
    winner = bets.upsert(
        fixture_id=1, player_discord_id=100, category="WINNER", payload_json="{}", now=NOW
    )
    winner.is_correct = True
    winner.points_awarded = 2
    winner.settled_at = NOW
    over_under = bets.upsert(
        fixture_id=1, player_discord_id=100, category="OVER_UNDER", payload_json="{}", now=NOW
    )
    over_under.is_correct = False
    over_under.points_awarded = 0
    over_under.settled_at = NOW
    # an unsettled bet on the open game -> excluded
    bets.upsert(fixture_id=2, player_discord_id=100, category="BTTS", payload_json="{}", now=NOW)
    session.flush()

    inputs = build_standing_inputs(session)
    assert len(inputs) == 2  # only the settled bets
    by_category = {i.category: i for i in inputs}
    assert by_category[BetCategory.WINNER].points == 2
    assert by_category[BetCategory.WINNER].is_correct is True
    assert by_category[BetCategory.OVER_UNDER].points == 0
    assert all(i.player_name == "Vitor" for i in inputs)
    assert all(i.player_created_at == NOW for i in inputs)


async def test_board_cog_registers_placar(tmp_path: Path) -> None:
    from tigrinho.bot.client import TigrinhoBot

    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    bot = TigrinhoBot(_settings())
    try:
        await bot.add_cog(
            BoardCog(bot, settings=_settings(), session_factory=create_session_factory(engine))
        )
        assert "placar" in {c.name for c in bot.tree.get_commands()}
    finally:
        await bot.close()
