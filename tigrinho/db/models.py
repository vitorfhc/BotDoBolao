"""SQLAlchemy 2.0 typed ORM models (see COMPLETION.md §6).

Identity columns use the provider/Discord ids directly (``fixture_id``, ``discord_id``);
``match_hash`` is a dedup/label only, never identity. Enum-like columns (``stage``,
``status``, ``category``) are stored as plain TEXT and given meaning by the domain/provider
layers. All datetimes are tz-aware UTC instants via :class:`TZDateTime`.

Grounded against SQLAlchemy 2.0 typed ORM:
https://docs.sqlalchemy.org/en/20/orm/quickstart.html
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .types import TZDateTime

# Map every ``Mapped[datetime]`` column to the UTC-normalizing TZDateTime (module-level
# so it is a name reference, not a mutable class-attribute literal).
_TYPE_ANNOTATION_MAP = {datetime: TZDateTime()}


class Base(DeclarativeBase):
    """Declarative base; maps Python ``datetime`` to UTC-normalizing :class:`TZDateTime`."""

    type_annotation_map = _TYPE_ANNOTATION_MAP


class Player(Base):
    """A bettor. Auto-created on the user's first bet (COMPLETION.md §6)."""

    __tablename__ = "players"

    discord_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    display_name: Mapped[str]
    created_at: Mapped[datetime]

    bets: Mapped[list[Bet]] = relationship(back_populates="player")


class Game(Base):
    """A World Cup fixture, keyed by the provider's canonical ``fixture_id``."""

    __tablename__ = "games"

    fixture_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    match_hash: Mapped[str]
    stage: Mapped[str]  # GROUP | KNOCKOUT
    home_team_id: Mapped[int]
    home_team_name: Mapped[str]
    away_team_id: Mapped[int]
    away_team_name: Mapped[str]
    kickoff_utc: Mapped[datetime]
    kickoff_local: Mapped[datetime]
    status: Mapped[str]  # SCHEDULED | LIVE | FINISHED | POSTPONED | CANCELLED | VOID
    home_goals_90: Mapped[int | None]
    away_goals_90: Mapped[int | None]
    advancing_team_id: Mapped[int | None]
    announced_at: Mapped[datetime | None]
    kickoff_announced_at: Mapped[datetime | None]
    last_announced_home_goals: Mapped[int | None]
    last_announced_away_goals: Mapped[int | None]
    settled_at: Mapped[datetime | None]

    bets: Mapped[list[Bet]] = relationship(back_populates="game")


class Bet(Base):
    """One prediction in one category for one game; unique per (game, player, category)."""

    __tablename__ = "bets"
    __table_args__ = (
        UniqueConstraint("fixture_id", "player_discord_id", "category", name="uq_bet_per_category"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("games.fixture_id"))
    player_discord_id: Mapped[int] = mapped_column(ForeignKey("players.discord_id"))
    category: Mapped[str]
    payload_json: Mapped[str]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
    is_correct: Mapped[bool | None]
    points_awarded: Mapped[int | None]
    settled_at: Mapped[datetime | None]

    game: Mapped[Game] = relationship(back_populates="bets")
    player: Mapped[Player] = relationship(back_populates="bets")


class ApiUsage(Base):
    """Per-day provider request counter for the budget hard-stop (COMPLETION.md §7.3)."""

    __tablename__ = "api_usage"

    budget_date: Mapped[date] = mapped_column(primary_key=True)
    count: Mapped[int] = mapped_column(default=0)
