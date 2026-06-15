"""TigrinhoDaCopa admin CLI (Typer) — COMPLETION.md §13.

Run inside the container: ``docker compose exec bot python -m tigrinho.cli <group> <command>``.
Shares the repositories and domain logic with the bot. Capability groups are added incrementally:
``games`` / ``players`` / ``bets`` (CRUD), manual result & re-settle, force-sync & cache, recalc &
dump. Destructive commands require a confirmation flag.

Tests override :func:`_open_session` to point at a temp database.
"""

from __future__ import annotations

from datetime import UTC, datetime

import typer
from sqlalchemy.orm import Session

from tigrinho.bot.poll_cog import apply_settlement
from tigrinho.config import load_settings
from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.repositories import GameRepository, PlayerRepository
from tigrinho.providers.base import GameStatus, GoalEvent, MatchResult, Stage

app = typer.Typer(help="TigrinhoDaCopa — CLI administrativa.", no_args_is_help=True)
games_app = typer.Typer(help="CRUD de jogos.", no_args_is_help=True)
players_app = typer.Typer(help="CRUD de jogadores.", no_args_is_help=True)
bets_app = typer.Typer(help="CRUD de apostas.", no_args_is_help=True)
result_app = typer.Typer(help="Resultado manual e reapuração.", no_args_is_help=True)
app.add_typer(games_app, name="games")
app.add_typer(players_app, name="players")
app.add_typer(bets_app, name="bets")
app.add_typer(result_app, name="result")


def _open_session() -> Session:
    """Open a DB session from the validated config (overridden in tests)."""
    settings = load_settings()
    engine = create_db_engine(settings.db_path)
    return create_session_factory(engine)()


def _utcnow() -> datetime:
    return datetime.now(UTC)


@games_app.command("list")
def games_list() -> None:
    """Lista todos os jogos (id, confronto, status, kickoff UTC)."""
    with _open_session() as session:
        games = GameRepository(session).list_all()
        if not games:
            typer.echo("(nenhum jogo)")
            return
        for game in games:
            typer.echo(
                f"{game.fixture_id}\t{game.home_team_name} x {game.away_team_name}\t"
                f"{game.status}\t{game.kickoff_utc.isoformat()}"
            )


@players_app.command("list")
def players_list() -> None:
    """Lista todos os jogadores (discord_id, nome)."""
    with _open_session() as session:
        players = PlayerRepository(session).list_all()
        if not players:
            typer.echo("(nenhum jogador)")
            return
        for player in players:
            typer.echo(f"{player.discord_id}\t{player.display_name}")


@result_app.command("set")
def result_set(
    fixture_id: int = typer.Argument(..., help="ID do jogo (fixture_id)."),
    home: int = typer.Argument(..., help="Gols do mandante nos 90'."),
    away: int = typer.Argument(..., help="Gols do visitante nos 90'."),
    scorer: int | None = typer.Option(None, "--scorer", help="player_id do 1º a marcar."),
    advancing: int | None = typer.Option(
        None, "--advancing", help="team_id que avança (mata-mata)."
    ),
) -> None:
    """Define o resultado dos 90' e (re)apura o jogo — idempotente (COMPLETION.md §13)."""
    with _open_session() as session:
        game = GameRepository(session).get(fixture_id)
        if game is None:
            typer.echo(f"Jogo {fixture_id} não encontrado.")
            raise typer.Exit(code=1)
        goals: tuple[GoalEvent, ...] = ()
        if scorer is not None:
            goals = (
                GoalEvent(
                    minute=1,
                    team_id=game.home_team_id,
                    player_id=scorer,
                    player_name=None,
                    is_own_goal=False,
                    is_penalty=False,
                ),
            )
        result = MatchResult(
            fixture_id=fixture_id,
            status=GameStatus.FINISHED,
            stage=Stage(game.stage),
            home_goals_90=home,
            away_goals_90=away,
            goals=goals,
            advancing_team_id=advancing,
        )
        settled = apply_settlement(session, result, now=_utcnow())
        session.commit()
        if settled is None:  # pragma: no cover - game existence already checked above
            typer.echo("Falha ao apurar.")
            raise typer.Exit(code=1)
        typer.echo(f"Apurado: {settled.home_team_name} {home}x{away} {settled.away_team_name}")
        for player_result in settled.players:
            typer.echo(f"  {player_result.player_discord_id}: {player_result.total_points} pt(s)")


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    app()
