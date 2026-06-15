"""Live polling & auto-settlement (COMPLETION.md §8.3, §9.2).

This module holds the pure/DB core — :func:`apply_settlement` (grade a finished game's bets and
update the game) and :func:`render_results_message` — kept Discord-free so they're tested against a
real session. The ``tasks.loop`` ``PollCog`` (active-window polling, provider calls via the budget,
posting results, stuck-game alerts) is layered on top.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from tigrinho.config import Settings
from tigrinho.db.repositories import BetRepository, GameRepository
from tigrinho.domain.bets import BetCategory
from tigrinho.domain.scoring import first_genuine_scorer
from tigrinho.domain.settlement import BetInput, match_facts_from_result, settle_game
from tigrinho.domain.text_pt import CATEGORY_LABELS_PT
from tigrinho.providers.base import FootballProvider, GameStatus, MatchResult


@dataclass(frozen=True, slots=True)
class PlayerResult:
    """One player's outcome for a settled game."""

    player_discord_id: int
    total_points: int
    lines: list[tuple[BetCategory, bool, int]]  # (category, is_correct, points)


@dataclass(frozen=True, slots=True)
class SettledGame:
    """Everything needed to post a game's results message."""

    fixture_id: int
    home_team_name: str
    away_team_name: str
    home_goals_90: int
    away_goals_90: int
    first_scorer_player_id: int | None
    players: list[PlayerResult]


def apply_settlement(session: Session, result: MatchResult, *, now: datetime) -> SettledGame | None:
    """Grade every bet for a finished game and update the game (idempotent). Returns ``None`` if
    the game is unknown. Raises ``ValueError`` if the 90' score is missing (caller treats as stuck).
    """
    game = GameRepository(session).get(result.fixture_id)
    if game is None:
        return None
    facts = match_facts_from_result(
        result, home_team_id=game.home_team_id, away_team_id=game.away_team_id
    )
    bet_rows = BetRepository(session).list_for_game(result.fixture_id)
    inputs = [
        BetInput(bet_id=row.id, category=BetCategory(row.category), payload_json=row.payload_json)
        for row in bet_rows
    ]
    outcomes = {outcome.bet_id: outcome for outcome in settle_game(facts, inputs)}

    by_player: dict[int, list[tuple[BetCategory, bool, int]]] = {}
    for row in bet_rows:
        outcome = outcomes[row.id]
        row.is_correct = outcome.is_correct
        row.points_awarded = outcome.points_awarded
        row.settled_at = now
        by_player.setdefault(row.player_discord_id, []).append(
            (BetCategory(row.category), outcome.is_correct, outcome.points_awarded)
        )

    first_scorer = first_genuine_scorer(result.goals)
    game.status = GameStatus.FINISHED.value
    game.home_goals_90 = facts.home_goals_90
    game.away_goals_90 = facts.away_goals_90
    game.advancing_team_id = result.advancing_team_id
    game.first_scorer_player_id = first_scorer
    game.settled_at = now
    session.flush()

    players = [
        PlayerResult(
            player_discord_id=player_id,
            total_points=sum(points for _, _, points in lines),
            lines=lines,
        )
        for player_id, lines in by_player.items()
    ]
    return SettledGame(
        fixture_id=result.fixture_id,
        home_team_name=game.home_team_name,
        away_team_name=game.away_team_name,
        home_goals_90=facts.home_goals_90,
        away_goals_90=facts.away_goals_90,
        first_scorer_player_id=first_scorer,
        players=players,
    )


async def collect_settlements(
    session: Session, provider: FootballProvider, settings: Settings, *, now: datetime
) -> list[SettledGame]:
    """Poll active games and settle any that are now finished (COMPLETION.md §9.2).

    If there are no active games, returns immediately **without any provider call**. For each
    finished active game, fetches the full result (goal timeline) and settles it. May raise
    ``BudgetExceeded`` from the provider (the cog turns it into a skip). No commit — caller commits.
    """
    games = GameRepository(session)
    active = games.list_active(now, settings.match_window_hours)
    if not active:
        return []
    active_ids = {game.fixture_id for game in active}
    settled: list[SettledGame] = []
    for result in await provider.get_live_results():
        if result.fixture_id not in active_ids:
            continue
        game = games.get(result.fixture_id)
        if game is not None:
            game.status = result.status.value
        if result.status is GameStatus.FINISHED:
            full_result = await provider.get_match_result(result.fixture_id)
            outcome = apply_settlement(session, full_result, now=now)
            if outcome is not None:
                settled.append(outcome)
    session.flush()
    return settled


def render_results_message(settled: SettledGame, *, scorer_name: str | None) -> str:
    """Render the pt-BR results message: 90' score, first scorer, each player's points (§8.3)."""
    lines = [
        f"🏁 **{settled.home_team_name} {settled.home_goals_90}x{settled.away_goals_90} "
        f"{settled.away_team_name}** — resultado final (90')"
    ]
    if settled.first_scorer_player_id is not None:
        shown = scorer_name if scorer_name is not None else f"#{settled.first_scorer_player_id}"
        lines.append(f"⚽ Primeiro a marcar: {shown}")
    else:
        lines.append("⚽ Primeiro a marcar: ninguém (0x0 ou só gol contra)")

    if settled.players:
        lines.append("🏆 **Pontos:**")
        for player in sorted(settled.players, key=lambda p: (-p.total_points, p.player_discord_id)):
            breakdown = ", ".join(
                f"{CATEGORY_LABELS_PT[category]} {'✅' if correct else '❌'}"
                for category, correct, _points in player.lines
            )
            lines.append(
                f"<@{player.player_discord_id}>: {player.total_points} pt(s) — {breakdown}"
            )
    return "\n".join(lines)
