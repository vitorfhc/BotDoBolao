"""Tests for pure pt-BR rendering of /minhas_apostas and /jogos (COMPLETION.md §8.2)."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from tigrinho.bot.bets_view import (
    STAGE_LABELS_PT,
    MyBetLine,
    OpenGameLine,
    render_my_bets,
    render_open_games,
)
from tigrinho.domain.bets import BetCategory
from tigrinho.providers.base import Stage

SP = ZoneInfo("America/Sao_Paulo")
KICK = datetime(2026, 6, 15, 19, 0, tzinfo=UTC)  # 16:00 SP


def test_stage_labels_cover_all() -> None:
    assert set(STAGE_LABELS_PT) == set(Stage)


def test_render_my_bets_empty() -> None:
    assert "ainda não" in render_my_bets([]).lower()


def test_render_my_bets_groups_open_and_settled() -> None:
    lines = [
        MyBetLine(
            matchup="Brasil x Argentina",
            category=BetCategory.WINNER,
            value="Mandante",
            settled=False,
            is_correct=None,
            points=None,
        ),
        MyBetLine(
            matchup="França x Alemanha",
            category=BetCategory.EXACT_SCORE,
            value="2x1",
            settled=True,
            is_correct=True,
            points=5,
        ),
        MyBetLine(
            matchup="França x Alemanha",
            category=BetCategory.OVER_UNDER,
            value="Menos de 2.5",
            settled=True,
            is_correct=False,
            points=0,
        ),
    ]
    text = render_my_bets(lines)
    assert "Abertas" in text
    assert "Apuradas" in text
    assert "Brasil x Argentina" in text
    assert "Vencedor: Mandante" in text
    assert "Placar exato: 2x1" in text
    assert "+5" in text  # correct settled bet shows points
    assert "❌" in text  # the wrong settled bet


def test_render_open_games_empty() -> None:
    assert "nenhum jogo" in render_open_games([], tz=SP).lower()


def test_render_open_games_shows_missing_categories() -> None:
    games = [
        OpenGameLine(
            matchup="Brasil x Argentina",
            kickoff_utc=KICK,
            stage=Stage.GROUP,
            bet_categories=frozenset({BetCategory.WINNER}),
        )
    ]
    text = render_open_games(games, tz=SP)
    assert "Brasil x Argentina" in text
    assert "16:00" in text  # localized
    assert "Fase de grupos" in text
    assert "falta palpitar" in text.lower()
    assert "Vencedor" not in text.split("falta palpitar")[1]  # already-bet category isn't "missing"


def test_render_open_games_all_predicted() -> None:
    games = [
        OpenGameLine(
            matchup="Brasil x Argentina",
            kickoff_utc=KICK,
            stage=Stage.KNOCKOUT,
            bet_categories=frozenset(BetCategory),
        )
    ]
    text = render_open_games(games, tz=SP)
    assert "tudo palpitado" in text.lower()
    assert "Mata-mata" in text
