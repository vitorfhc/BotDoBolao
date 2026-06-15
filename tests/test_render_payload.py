"""Tests for human-readable pt-BR rendering of bet payloads (COMPLETION.md §8.2)."""

from __future__ import annotations

from tigrinho.domain.bets import (
    BttsPayload,
    BttsSelection,
    ExactScorePayload,
    FirstScorerPayload,
    OverUnderPayload,
    OverUnderSelection,
    WinnerPayload,
    WinnerSelection,
)
from tigrinho.domain.text_pt import (
    BTTS_LABELS_PT,
    OVER_UNDER_LABELS_PT,
    WINNER_LABELS_PT,
    render_payload,
)


def test_labels_cover_all_selections() -> None:
    assert set(BTTS_LABELS_PT) == set(BttsSelection)
    assert set(WINNER_LABELS_PT) == set(WinnerSelection)
    assert set(OVER_UNDER_LABELS_PT) == set(OverUnderSelection)


def test_render_exact_score() -> None:
    assert render_payload(ExactScorePayload(2, 1)) == "2x1"


def test_render_first_scorer_with_and_without_name() -> None:
    assert render_payload(FirstScorerPayload(7), scorer_name="Neymar") == "Neymar"
    assert render_payload(FirstScorerPayload(7)) == "#7"


def test_render_btts() -> None:
    assert render_payload(BttsPayload(BttsSelection.BOTH)) == BTTS_LABELS_PT[BttsSelection.BOTH]
    assert "mandante" in render_payload(BttsPayload(BttsSelection.ONLY_HOME)).lower()


def test_render_winner() -> None:
    assert render_payload(WinnerPayload(WinnerSelection.HOME)) == "Mandante"
    assert render_payload(WinnerPayload(WinnerSelection.DRAW)) == "Empate"
    assert render_payload(WinnerPayload(WinnerSelection.AWAY)) == "Visitante"


def test_render_over_under() -> None:
    assert render_payload(OverUnderPayload(OverUnderSelection.OVER)) == "Mais de 2.5"
    assert render_payload(OverUnderPayload(OverUnderSelection.UNDER)) == "Menos de 2.5"


def test_render_winner_with_team_names() -> None:
    home, away = "Brasil", "Argentina"
    assert (
        render_payload(WinnerPayload(WinnerSelection.HOME), home_name=home, away_name=away)
        == "Brasil"
    )
    assert (
        render_payload(WinnerPayload(WinnerSelection.AWAY), home_name=home, away_name=away)
        == "Argentina"
    )
    assert (
        render_payload(WinnerPayload(WinnerSelection.DRAW), home_name=home, away_name=away)
        == "Empate"
    )


def test_render_btts_with_team_names_drops_gendered_article() -> None:
    # "Só a França" would need a feminine article we can't know — drop it.
    assert (
        render_payload(BttsPayload(BttsSelection.ONLY_HOME), home_name="Brasil", away_name="França")
        == "Só Brasil"
    )
    assert (
        render_payload(BttsPayload(BttsSelection.ONLY_AWAY), home_name="Brasil", away_name="França")
        == "Só França"
    )
