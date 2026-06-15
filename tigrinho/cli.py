"""TigrinhoDaCopa admin CLI (Typer) — COMPLETION.md §13.

Run inside the container: ``docker compose exec bot python -m tigrinho.cli <group> <command>``.
Shares the repositories and domain logic with the bot. Capability groups are added incrementally:
``games`` / ``players`` / ``bets`` (CRUD), manual result & re-settle, force-sync & cache, recalc &
dump. Destructive commands require a confirmation flag.

Tests override :func:`_open_session` to point at a temp database.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Literal

import typer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tigrinho.bootstrap import build_provider
from tigrinho.bot.board_cog import Period, build_standing_inputs, compute_standings
from tigrinho.bot.poll_cog import apply_settlement
from tigrinho.bot.sync_cog import collect_sync_messages
from tigrinho.config import Settings, load_settings
from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import ApiUsage, Bet, Game, Player
from tigrinho.db.models import SquadPlayer as SquadPlayerRow
from tigrinho.db.repositories import (
    ApiUsageRepository,
    BetRepository,
    GameRepository,
    PlayerRepository,
    SquadRepository,
)
from tigrinho.providers.base import FootballProvider, GameStatus, MatchResult, Stage

app = typer.Typer(help="TigrinhoDaCopa — CLI administrativa.", no_args_is_help=True)
games_app = typer.Typer(help="CRUD de jogos.", no_args_is_help=True)
players_app = typer.Typer(help="CRUD de jogadores.", no_args_is_help=True)
bets_app = typer.Typer(help="CRUD de apostas.", no_args_is_help=True)
result_app = typer.Typer(help="Resultado manual e reapuração.", no_args_is_help=True)
budget_app = typer.Typer(help="Orçamento de requisições da API.", no_args_is_help=True)
board_app = typer.Typer(help="Recalcular o placar.", no_args_is_help=True)
squads_app = typer.Typer(help="Cache de elencos.", no_args_is_help=True)
sync_app = typer.Typer(help="Sincronização de jogos.", no_args_is_help=True)
db_app = typer.Typer(help="Inspeção do banco de dados.", no_args_is_help=True)
app.add_typer(games_app, name="games")
app.add_typer(players_app, name="players")
app.add_typer(bets_app, name="bets")
app.add_typer(result_app, name="result")
app.add_typer(budget_app, name="budget")
app.add_typer(board_app, name="board")
app.add_typer(squads_app, name="squads")
app.add_typer(sync_app, name="sync")
app.add_typer(db_app, name="db")


def _settings() -> Settings:
    """Load the validated config (overridden in tests)."""
    return load_settings()


def _open_session() -> Session:
    """Open a DB session from the validated config (overridden in tests)."""
    engine = create_db_engine(_settings().db_path)
    return create_session_factory(engine)()


def _build_provider(settings: Settings, session: Session) -> FootballProvider:
    """Build the configured provider for a one-shot CLI call (overridden in tests)."""
    return build_provider(settings, session)


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


@games_app.command("show")
def games_show(fixture_id: int = typer.Argument(..., help="ID do jogo (fixture_id).")) -> None:
    """Mostra os detalhes de um jogo."""
    with _open_session() as session:
        game = GameRepository(session).get(fixture_id)
        if game is None:
            typer.echo(f"Jogo {fixture_id} não encontrado.")
            raise typer.Exit(code=1)
        typer.echo(f"fixture_id: {game.fixture_id}")
        typer.echo(f"confronto: {game.home_team_name} x {game.away_team_name}")
        typer.echo(f"stage: {game.stage}")
        typer.echo(f"status: {game.status}")
        typer.echo(f"kickoff_utc: {game.kickoff_utc.isoformat()}")
        typer.echo(f"placar 90': {game.home_goals_90}-{game.away_goals_90}")
        typer.echo(f"primeiro a marcar: {game.first_scorer_player_id}")
        typer.echo(f"settled_at: {game.settled_at}")


@bets_app.command("list")
def bets_list(
    game: int | None = typer.Option(None, "--game", help="Filtrar por fixture_id."),
    player: int | None = typer.Option(None, "--player", help="Filtrar por player_discord_id."),
) -> None:
    """Lista apostas (todas, ou filtradas por jogo/jogador)."""
    with _open_session() as session:
        repo = BetRepository(session)
        if game is not None:
            bets = repo.list_for_game(game)
        elif player is not None:
            bets = repo.list_for_player(player)
        else:
            bets = repo.list_all()
        if not bets:
            typer.echo("(nenhuma aposta)")
            return
        for bet in bets:
            typer.echo(
                f"{bet.id}\tfix={bet.fixture_id}\tplayer={bet.player_discord_id}\t"
                f"{bet.category}\t{bet.payload_json}\tcorrect={bet.is_correct}\t"
                f"pts={bet.points_awarded}"
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
        result = MatchResult(
            fixture_id=fixture_id,
            status=GameStatus.FINISHED,
            stage=Stage(game.stage),
            home_goals_90=home,
            away_goals_90=away,
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


@budget_app.command("show")
def budget_show() -> None:
    """Mostra o uso de requisições da API hoje e quanto resta (COMPLETION.md §7.3)."""
    settings = _settings()
    today = _utcnow().astimezone(settings.budget_reset_tzinfo).date()
    with _open_session() as session:
        count = ApiUsageRepository(session).get_count(today)
    remaining = max(0, settings.api_daily_cap - count)
    typer.echo(
        f"API hoje ({today.isoformat()}): {count}/{settings.api_daily_cap} — restam {remaining}"
    )


@board_app.command("recalc")
def board_recalc(
    periodo: Literal["geral", "semana"] = typer.Option(
        "geral", "--periodo", help="geral (padrão) ou semana"
    ),
) -> None:
    """Recalcula o placar do zero a partir das apostas apuradas (COMPLETION.md §10, §13)."""
    settings = _settings()
    with _open_session() as session:
        rows = build_standing_inputs(session)
    standings = compute_standings(rows, period=Period(periodo), tz=settings.tzinfo, now=_utcnow())
    if not standings:
        typer.echo("(sem pontos ainda)")
        return
    for row in standings:
        typer.echo(
            f"{row.rank}\t{row.player_name}\t{row.total_points} pt\t"
            f"(exatos {row.exact_hits}, acertos {row.correct_bets})"
        )


@squads_app.command("seed")
def squads_seed(team_id: int = typer.Argument(..., help="team_id do time a cadastrar.")) -> None:
    """Busca o elenco no provider e o cacheia (necessário para 'primeiro a marcar' — §13)."""
    settings = _settings()
    with _open_session() as session:
        provider = _build_provider(settings, session)
        players = asyncio.run(provider.get_squad(team_id))
        rows = [
            SquadPlayerRow(player_id=p.player_id, team_id=team_id, name=p.name, position=p.position)
            for p in players
        ]
        count = SquadRepository(session).replace_team(team_id, rows)
        session.commit()
    typer.echo(f"Elenco do time {team_id}: {count} jogador(es) cadastrado(s).")


@sync_app.command("run")
def sync_run() -> None:
    """Força a sincronização de jogos agora (insere/atualiza/anula) — §13."""
    settings = _settings()
    with _open_session() as session:
        provider = _build_provider(settings, session)
        messages = asyncio.run(collect_sync_messages(session, provider, settings, now=_utcnow()))
        session.commit()
    typer.echo(f"Sincronização concluída: {len(messages)} aviso(s).")
    for message in messages:
        typer.echo(message)


@bets_app.command("delete")
def bets_delete(
    bet_id: int = typer.Argument(..., help="ID da aposta a apagar."),
    confirm: bool = typer.Option(False, "--confirm", help="Confirma a remoção (obrigatório)."),
) -> None:
    """Apaga uma aposta (admin; exige --confirm — COMPLETION.md §13)."""
    if not confirm:
        typer.echo("Operação destrutiva — use --confirm para apagar a aposta.")
        raise typer.Exit(code=1)
    with _open_session() as session:
        repo = BetRepository(session)
        bet = repo.get(bet_id)
        if bet is None:
            typer.echo(f"Aposta {bet_id} não encontrada.")
            raise typer.Exit(code=1)
        repo.delete(bet)
        session.commit()
    typer.echo(f"Aposta {bet_id} apagada.")


@db_app.command("dump")
def db_dump() -> None:
    """Imprime a contagem de linhas de cada tabela (visão geral para debug — §13)."""
    models = (Player, Game, Bet, SquadPlayerRow, ApiUsage)
    with _open_session() as session:
        for model in models:
            count = session.scalar(select(func.count()).select_from(model)) or 0
            typer.echo(f"{model.__tablename__}\t{count}")


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    app()
