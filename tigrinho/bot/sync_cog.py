"""Daily fixtures sync (COMPLETION.md §9.1).

This module currently holds :func:`apply_plan` — the DB-mutation half of a sync, kept free of any
Discord dependency so it can be tested against a real SQLite session. The :class:`SyncCog`
(``tasks.loop`` scheduling, provider fetch via the budget, and announcement sending) is layered on
top of this.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, tzinfo

from sqlalchemy.orm import Session

from tigrinho.db.models import Game
from tigrinho.db.repositories import BetRepository, GameRepository
from tigrinho.providers.base import Fixture, GameStatus

from .sync_planning import SyncPlan, compute_match_hash


@dataclass(frozen=True, slots=True)
class AppliedSync:
    """Counts of what a sync applied (for logging)."""

    new: int
    rescheduled: int
    voided: int


def _game_from_fixture(fixture: Fixture, tz: tzinfo) -> Game:
    return Game(
        fixture_id=fixture.fixture_id,
        match_hash=compute_match_hash(
            fixture.kickoff_utc, fixture.home_team_id, fixture.away_team_id
        ),
        stage=fixture.stage.value,
        home_team_id=fixture.home_team_id,
        home_team_name=fixture.home_team_name,
        away_team_id=fixture.away_team_id,
        away_team_name=fixture.away_team_name,
        kickoff_utc=fixture.kickoff_utc,
        kickoff_local=fixture.kickoff_utc.astimezone(tz),
        status=fixture.status.value,
        home_goals_90=None,
        away_goals_90=None,
        advancing_team_id=None,
        first_scorer_player_id=None,
        announced_at=None,
        settled_at=None,
    )


def apply_plan(session: Session, plan: SyncPlan, *, now: datetime, tz: tzinfo) -> AppliedSync:
    """Apply a :class:`SyncPlan` to the DB (insert new, update rescheduled, void cancelled).

    Voiding a game sets it ``VOID`` + ``settled_at`` (so it drops out of open/active queries) and
    voids its bets (0 points, no longer gradable). The caller commits and sends the announcements.
    """
    games = GameRepository(session)
    bets = BetRepository(session)

    for fixture in plan.new:
        games.add(_game_from_fixture(fixture, tz))

    for fixture in plan.rescheduled:
        game = games.get(fixture.fixture_id)
        if game is not None:
            game.kickoff_utc = fixture.kickoff_utc
            game.kickoff_local = fixture.kickoff_utc.astimezone(tz)
            game.match_hash = compute_match_hash(
                fixture.kickoff_utc, fixture.home_team_id, fixture.away_team_id
            )
            game.status = GameStatus.SCHEDULED.value

    for fixture in plan.voided:
        game = games.get(fixture.fixture_id)
        if game is not None:
            game.status = GameStatus.VOID.value
            game.settled_at = now
            for bet in bets.list_for_game(fixture.fixture_id):
                bet.is_correct = None
                bet.points_awarded = 0
                bet.settled_at = now

    session.flush()
    return AppliedSync(
        new=len(plan.new), rescheduled=len(plan.rescheduled), voided=len(plan.voided)
    )
