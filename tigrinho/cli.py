"""TigrinhoDaCopa admin CLI (Typer) — COMPLETION.md §13.

Run inside the container: ``docker compose exec bot python -m tigrinho.cli <group> <command>``.
Shares the repositories and domain logic with the bot. Capability groups are added incrementally:
``games`` / ``players`` / ``bets`` (CRUD), manual result & re-settle, force-sync & cache, recalc &
dump. Destructive commands require a confirmation flag.

Tests override :func:`_open_session` to point at a temp database.
"""

from __future__ import annotations

import typer
from sqlalchemy.orm import Session

from tigrinho.config import load_settings
from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.repositories import GameRepository, PlayerRepository

app = typer.Typer(help="TigrinhoDaCopa — CLI administrativa.", no_args_is_help=True)
games_app = typer.Typer(help="CRUD de jogos.", no_args_is_help=True)
players_app = typer.Typer(help="CRUD de jogadores.", no_args_is_help=True)
bets_app = typer.Typer(help="CRUD de apostas.", no_args_is_help=True)
app.add_typer(games_app, name="games")
app.add_typer(players_app, name="players")
app.add_typer(bets_app, name="bets")


def _open_session() -> Session:
    """Open a DB session from the validated config (overridden in tests)."""
    settings = load_settings()
    engine = create_db_engine(settings.db_path)
    return create_session_factory(engine)()


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


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    app()
