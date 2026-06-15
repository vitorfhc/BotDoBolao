"""Tests for bet placement/deletion + time-based closing (COMPLETION.md §8.2)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from tigrinho.bot.bets_logic import (
    GameNotFoundError,
    GameNotOpenError,
    delete_bet,
    place_bet,
)
from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import Base, Game
from tigrinho.db.repositories import BetRepository, PlayerRepository
from tigrinho.domain.bets import (
    BetCategory,
    WinnerPayload,
    WinnerSelection,
    dump_payload,
    is_bet_open,
)

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
OPEN_KICK = NOW + timedelta(hours=5)
CLOSED_KICK = NOW - timedelta(hours=1)
WINNER_HOME = WinnerPayload(WinnerSelection.HOME)


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    with create_session_factory(engine)() as s:
        yield s


def _add_game(session: Session, fixture_id: int, kickoff: datetime) -> None:
    session.add(
        Game(
            fixture_id=fixture_id,
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
            announced_at=None,
            settled_at=None,
        )
    )
    session.flush()


def test_is_bet_open_closes_at_kickoff() -> None:
    assert is_bet_open(OPEN_KICK, NOW) is True
    assert is_bet_open(NOW, NOW) is False  # closes exactly at kickoff
    assert is_bet_open(CLOSED_KICK, NOW) is False


def test_place_bet_creates_player_and_bet(session: Session) -> None:
    _add_game(session, 1, OPEN_KICK)
    bet = place_bet(
        session,
        fixture_id=1,
        player_discord_id=100,
        display_name="Vitor",
        category=BetCategory.WINNER,
        payload=WINNER_HOME,
        now=NOW,
    )
    assert bet.payload_json == dump_payload(WINNER_HOME)
    assert PlayerRepository(session).get(100) is not None


def test_place_bet_edits_existing(session: Session) -> None:
    _add_game(session, 1, OPEN_KICK)
    place_bet(
        session,
        fixture_id=1,
        player_discord_id=100,
        display_name="Vitor",
        category=BetCategory.WINNER,
        payload=WINNER_HOME,
        now=NOW,
    )
    edited = place_bet(
        session,
        fixture_id=1,
        player_discord_id=100,
        display_name="Vitor",
        category=BetCategory.WINNER,
        payload=WinnerPayload(WinnerSelection.AWAY),
        now=NOW + timedelta(minutes=1),
    )
    assert edited.payload_json == dump_payload(WinnerPayload(WinnerSelection.AWAY))
    assert len(BetRepository(session).list_for_game(1)) == 1  # still one bet


def test_place_bet_rejects_closed_game(session: Session) -> None:
    _add_game(session, 1, CLOSED_KICK)
    with pytest.raises(GameNotOpenError):
        place_bet(
            session,
            fixture_id=1,
            player_discord_id=100,
            display_name="Vitor",
            category=BetCategory.WINNER,
            payload=WINNER_HOME,
            now=NOW,
        )


def test_place_bet_unknown_game(session: Session) -> None:
    with pytest.raises(GameNotFoundError):
        place_bet(
            session,
            fixture_id=999,
            player_discord_id=100,
            display_name="Vitor",
            category=BetCategory.WINNER,
            payload=WINNER_HOME,
            now=NOW,
        )


def test_delete_bet_open(session: Session) -> None:
    _add_game(session, 1, OPEN_KICK)
    place_bet(
        session,
        fixture_id=1,
        player_discord_id=100,
        display_name="Vitor",
        category=BetCategory.WINNER,
        payload=WINNER_HOME,
        now=NOW,
    )
    assert (
        delete_bet(
            session, fixture_id=1, player_discord_id=100, category=BetCategory.WINNER, now=NOW
        )
        is True
    )
    assert BetRepository(session).get_for(1, 100, "WINNER") is None


def test_delete_bet_missing_returns_false(session: Session) -> None:
    _add_game(session, 1, OPEN_KICK)
    assert (
        delete_bet(
            session, fixture_id=1, player_discord_id=100, category=BetCategory.WINNER, now=NOW
        )
        is False
    )


def test_delete_bet_rejects_closed_game(session: Session) -> None:
    _add_game(session, 1, CLOSED_KICK)
    with pytest.raises(GameNotOpenError):
        delete_bet(
            session, fixture_id=1, player_discord_id=100, category=BetCategory.WINNER, now=NOW
        )
