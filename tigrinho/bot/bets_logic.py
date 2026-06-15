"""Bet placement/deletion CRUD with time-based closing (COMPLETION.md §8.2).

Pure DB logic (no Discord): the cogs collect+validate the payload, then call these to upsert/delete
a bet. Closing is purely time-based (``now < kickoff_utc``) and never consumes the API budget.
Errors carry pt-BR messages the cog shows the user.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from tigrinho.db.models import Bet
from tigrinho.db.repositories import BetRepository, GameRepository, PlayerRepository
from tigrinho.domain.bets import BetCategory, BetPayload, dump_payload, is_bet_open


class BetError(Exception):
    """Base for bet CRUD errors; ``str(error)`` is a pt-BR message for the user."""


class GameNotFoundError(BetError):
    def __init__(self) -> None:
        super().__init__("Jogo não encontrado.")


class GameNotOpenError(BetError):
    def __init__(self) -> None:
        super().__init__("As apostas para este jogo já fecharam (o jogo já começou).")


def place_bet(
    session: Session,
    *,
    fixture_id: int,
    player_discord_id: int,
    display_name: str,
    category: BetCategory,
    payload: BetPayload,
    now: datetime,
) -> Bet:
    """Create or edit a bet for an open game (auto-creates the player); raises if closed/missing."""
    game = GameRepository(session).get(fixture_id)
    if game is None:
        raise GameNotFoundError
    if not is_bet_open(game.kickoff_utc, now):
        raise GameNotOpenError
    PlayerRepository(session).get_or_create(player_discord_id, display_name, now=now)
    return BetRepository(session).upsert(
        fixture_id=fixture_id,
        player_discord_id=player_discord_id,
        category=category.value,
        payload_json=dump_payload(payload),
        now=now,
    )


def delete_bet(
    session: Session,
    *,
    fixture_id: int,
    player_discord_id: int,
    category: BetCategory,
    now: datetime,
) -> bool:
    """Delete a caller's bet for an open game. Returns False if there was no such bet."""
    game = GameRepository(session).get(fixture_id)
    if game is None:
        raise GameNotFoundError
    if not is_bet_open(game.kickoff_utc, now):
        raise GameNotOpenError
    bets = BetRepository(session)
    bet = bets.get_for(fixture_id, player_discord_id, category.value)
    if bet is None:
        return False
    bets.delete(bet)
    session.flush()
    return True
