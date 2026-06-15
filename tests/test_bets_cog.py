"""Tests for /minhas_apostas + /jogos DB-build helpers and BetsCog wiring (COMPLETION.md §8.2)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from tigrinho.bot.bets_cog import BetsCog, build_my_bet_lines, build_open_game_lines
from tigrinho.config import Settings
from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import Base, Game
from tigrinho.db.repositories import BetRepository, PlayerRepository
from tigrinho.domain.bets import (
    BetCategory,
    ExactScorePayload,
    FirstScorerPayload,
    WinnerPayload,
    WinnerSelection,
    dump_payload,
)

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


def _add_game(session: Session, fid: int, *, kickoff: datetime, settled: datetime | None) -> None:
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


def _seed(session: Session) -> None:
    _add_game(session, 1, kickoff=NOW + timedelta(hours=5), settled=None)  # open
    _add_game(session, 2, kickoff=NOW - timedelta(hours=3), settled=NOW - timedelta(hours=1))
    PlayerRepository(session).get_or_create(100, "Vitor", now=NOW)
    bets = BetRepository(session)
    bets.upsert(
        fixture_id=1,
        player_discord_id=100,
        category="WINNER",
        payload_json=dump_payload(WinnerPayload(WinnerSelection.HOME)),
        now=NOW,
    )
    bets.upsert(
        fixture_id=1,
        player_discord_id=100,
        category="FIRST_SCORER",
        payload_json=dump_payload(FirstScorerPayload(7)),
        now=NOW,
    )
    settled_bet = bets.upsert(
        fixture_id=2,
        player_discord_id=100,
        category="EXACT_SCORE",
        payload_json=dump_payload(ExactScorePayload(2, 1)),
        now=NOW,
    )
    settled_bet.is_correct = True
    settled_bet.points_awarded = 5
    settled_bet.settled_at = NOW
    session.flush()


def test_build_my_bet_lines(session: Session) -> None:
    _seed(session)
    lines = build_my_bet_lines(session, 100, scorer_resolver={7: "Neymar"}.get)
    by_cat = {line.category: line for line in lines}
    assert by_cat[BetCategory.FIRST_SCORER].value == "Neymar"  # resolved scorer name
    assert by_cat[BetCategory.WINNER].value == "Mandante"
    assert by_cat[BetCategory.WINNER].settled is False
    settled = by_cat[BetCategory.EXACT_SCORE]
    assert settled.settled is True
    assert settled.is_correct is True
    assert settled.points == 5


def test_build_open_game_lines(session: Session) -> None:
    _seed(session)
    lines = build_open_game_lines(session, 100, now=NOW)
    assert len(lines) == 1  # only the open game
    assert lines[0].matchup == "Brasil x Argentina"
    assert lines[0].bet_categories == frozenset({BetCategory.WINNER, BetCategory.FIRST_SCORER})


def test_build_open_game_lines_no_bets(session: Session) -> None:
    _add_game(session, 1, kickoff=NOW + timedelta(hours=5), settled=None)
    lines = build_open_game_lines(session, 999, now=NOW)
    assert len(lines) == 1
    assert lines[0].bet_categories == frozenset()


async def test_bets_cog_registers_read_commands(tmp_path: Path) -> None:
    from tigrinho.bot.client import TigrinhoBot

    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    bot = TigrinhoBot(_settings())
    try:
        await bot.add_cog(
            BetsCog(bot, settings=_settings(), session_factory=create_session_factory(engine))
        )
        names = {command.name for command in bot.tree.get_commands()}
        assert {"minhas_apostas", "jogos"} <= names
    finally:
        await bot.close()
