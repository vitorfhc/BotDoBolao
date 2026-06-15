"""Tests for pt-BR templates — the /ajuda help text must cover everything in §11."""

from __future__ import annotations

from tigrinho.domain.bets import BetCategory
from tigrinho.domain.scoring import POINTS
from tigrinho.domain.text_pt import CATEGORY_LABELS_PT, help_text

ALL_COMMANDS = [
    "/apostar",
    "/minhas_apostas",
    "/jogos",
    "/placar",
    "/inscrever",
    "/sair",
    "/ajuda",
]


def test_every_category_has_a_label() -> None:
    assert set(CATEGORY_LABELS_PT) == set(BetCategory)


def test_help_lists_every_command() -> None:
    text = help_text()
    for command in ALL_COMMANDS:
        assert command in text


def test_help_shows_each_category_with_its_points() -> None:
    text = help_text()
    lines = text.splitlines()
    for category, points in POINTS.items():
        label = CATEGORY_LABELS_PT[category]
        # the category's label and its points value must appear on the same line
        category_line = next((line for line in lines if label in line), None)
        assert category_line is not None, f"missing line for {label}"
        assert str(points) in category_line


def test_help_explains_key_rules() -> None:
    text = help_text().lower()
    assert "mata-mata" in text  # knockout
    assert "90" in text  # 90-minute rule
    assert "fecha" in text or "apito" in text  # bets close at kickoff
    assert "tigrinhos" in text  # the notifications role
    # role is notifications-only / not required to bet
    assert "qualquer pessoa" in text or "não é necessário" in text


def test_help_mentions_no_real_money() -> None:
    text = help_text().lower()
    assert "dinheiro" in text or "diversão" in text


def test_help_fits_discord_embed_description_limit() -> None:
    # Discord embed description limit is 4096 chars.
    assert len(help_text()) <= 4096
