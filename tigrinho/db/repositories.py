"""Typed CRUD repositories over the ORM models (COMPLETION.md §5, §6).

Each repository wraps a single :class:`~sqlalchemy.orm.Session`. Repositories ``flush`` so
freshly-created rows are usable within the transaction, but they never ``commit`` — the caller
(a cog or the CLI) owns the transaction boundary. Timestamps are passed in explicitly (no hidden
clock) so callers stay deterministic and testable.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import ApiUsage, Bet, Game, Player, SquadPlayer


class PlayerRepository:
    """Players are auto-created on a user's first bet (COMPLETION.md §6)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, discord_id: int) -> Player | None:
        return self.session.get(Player, discord_id)

    def get_or_create(self, discord_id: int, display_name: str, *, now: datetime) -> Player:
        player = self.get(discord_id)
        if player is None:
            player = Player(discord_id=discord_id, display_name=display_name, created_at=now)
            self.session.add(player)
            self.session.flush()
            return player
        if player.display_name != display_name:
            player.display_name = display_name
            self.session.flush()
        return player

    def list_all(self) -> list[Player]:
        return list(self.session.scalars(select(Player).order_by(Player.created_at)))


class GameRepository:
    """Games keyed by the provider's canonical ``fixture_id``."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, fixture_id: int) -> Game | None:
        return self.session.get(Game, fixture_id)

    def add(self, game: Game) -> None:
        self.session.add(game)
        self.session.flush()

    def list_all(self) -> list[Game]:
        return list(self.session.scalars(select(Game).order_by(Game.kickoff_utc)))

    def list_open(self, now: datetime) -> list[Game]:
        """Games still open for bets: kickoff in the future and not yet settled/voided."""
        stmt = (
            select(Game)
            .where(Game.settled_at.is_(None), Game.kickoff_utc > now)
            .order_by(Game.kickoff_utc)
        )
        return list(self.session.scalars(stmt))

    def list_active(self, now: datetime, window_hours: int) -> list[Game]:
        """Games to poll: kicked off, still inside the match window, not yet settled (§9.2)."""
        earliest_kickoff = now - timedelta(hours=window_hours)
        stmt = (
            select(Game)
            .where(
                Game.settled_at.is_(None),
                Game.kickoff_utc <= now,
                Game.kickoff_utc >= earliest_kickoff,
            )
            .order_by(Game.kickoff_utc)
        )
        return list(self.session.scalars(stmt))

    def list_stuck(self, now: datetime, window_hours: int) -> list[Game]:
        """Unsettled games already past their match window (need manual settlement — §9.2)."""
        cutoff = now - timedelta(hours=window_hours)
        stmt = (
            select(Game)
            .where(Game.settled_at.is_(None), Game.kickoff_utc < cutoff)
            .order_by(Game.kickoff_utc)
        )
        return list(self.session.scalars(stmt))


class BetRepository:
    """One bet per (game, player, category); editing overwrites in place (COMPLETION.md §8)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, bet_id: int) -> Bet | None:
        return self.session.get(Bet, bet_id)

    def get_for(self, fixture_id: int, player_discord_id: int, category: str) -> Bet | None:
        stmt = select(Bet).where(
            Bet.fixture_id == fixture_id,
            Bet.player_discord_id == player_discord_id,
            Bet.category == category,
        )
        return self.session.scalars(stmt).one_or_none()

    def upsert(
        self,
        *,
        fixture_id: int,
        player_discord_id: int,
        category: str,
        payload_json: str,
        now: datetime,
    ) -> Bet:
        """Create the bet, or overwrite the existing one's payload (editing reuses the flow)."""
        existing = self.get_for(fixture_id, player_discord_id, category)
        if existing is not None:
            existing.payload_json = payload_json
            existing.updated_at = now
            self.session.flush()
            return existing
        bet = Bet(
            fixture_id=fixture_id,
            player_discord_id=player_discord_id,
            category=category,
            payload_json=payload_json,
            created_at=now,
            updated_at=now,
            is_correct=None,
            points_awarded=None,
            settled_at=None,
        )
        self.session.add(bet)
        self.session.flush()
        return bet

    def list_for_player(self, player_discord_id: int) -> list[Bet]:
        stmt = (
            select(Bet)
            .where(Bet.player_discord_id == player_discord_id)
            .order_by(Bet.fixture_id, Bet.category)
        )
        return list(self.session.scalars(stmt))

    def list_for_game(self, fixture_id: int) -> list[Bet]:
        stmt = (
            select(Bet)
            .where(Bet.fixture_id == fixture_id)
            .order_by(Bet.player_discord_id, Bet.category)
        )
        return list(self.session.scalars(stmt))

    def delete(self, bet: Bet) -> None:
        self.session.delete(bet)


class SquadRepository:
    """Cached team rosters for first-scorer selection; seeded/refreshed via the CLI (§13)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, player_id: int) -> SquadPlayer | None:
        return self.session.get(SquadPlayer, player_id)

    def list_for_team(self, team_id: int) -> list[SquadPlayer]:
        stmt = select(SquadPlayer).where(SquadPlayer.team_id == team_id).order_by(SquadPlayer.name)
        return list(self.session.scalars(stmt))

    def replace_team(self, team_id: int, players: Iterable[SquadPlayer]) -> int:
        """Replace a team's cached roster (drop existing rows, insert the given ones)."""
        for existing in self.list_for_team(team_id):
            self.session.delete(existing)
        self.session.flush()  # deletes land before inserts so reused player ids don't collide
        count = 0
        for player in players:
            self.session.add(player)
            count += 1
        self.session.flush()
        return count

    def count(self) -> int:
        total = self.session.scalar(select(func.count()).select_from(SquadPlayer))
        return total or 0


class ApiUsageRepository:
    """Per-day provider request counter backing the budget hard-stop (COMPLETION.md §7.3)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_count(self, budget_date: date) -> int:
        row = self.session.get(ApiUsage, budget_date)
        return row.count if row is not None else 0

    def increment(self, budget_date: date) -> int:
        """Increment (creating the row if needed) and return the new count for the day."""
        row = self.session.get(ApiUsage, budget_date)
        if row is None:
            row = ApiUsage(budget_date=budget_date, count=1)
            self.session.add(row)
        else:
            row.count += 1
        self.session.flush()
        return row.count
