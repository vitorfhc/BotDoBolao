"""Tests for the pure /apostar helpers: knockout draw-hiding, pagination, labels (§8.1, §8.2)."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from tigrinho.bot.apostar_view import (
    DISCORD_SELECT_LIMIT,
    Matchup,
    game_choice_label,
    paginate,
    winner_selection_options,
)
from tigrinho.domain.bets import WinnerSelection
from tigrinho.providers.base import Stage

SP = ZoneInfo("America/Sao_Paulo")


def test_winner_options_group_includes_draw() -> None:
    assert winner_selection_options(Stage.GROUP) == [
        WinnerSelection.HOME,
        WinnerSelection.DRAW,
        WinnerSelection.AWAY,
    ]


def test_winner_options_knockout_hides_draw() -> None:
    options = winner_selection_options(Stage.KNOCKOUT)
    assert WinnerSelection.DRAW not in options
    assert options == [WinnerSelection.HOME, WinnerSelection.AWAY]


def test_paginate_chunks_by_limit() -> None:
    items = list(range(30))
    pages = paginate(items)
    assert len(pages) == 2
    assert len(pages[0]) == DISCORD_SELECT_LIMIT
    assert len(pages[1]) == 5
    assert [x for page in pages for x in page] == items  # nothing lost or reordered


def test_paginate_exact_multiple() -> None:
    assert len(paginate(list(range(25)))) == 1


def test_paginate_empty_yields_one_empty_page() -> None:
    assert paginate([]) == [[]]


def test_game_choice_label() -> None:
    kickoff_local = datetime(2026, 6, 15, 19, 0, tzinfo=UTC).astimezone(SP)  # 16:00 SP
    label = game_choice_label("Brasil", "Argentina", kickoff_local)
    assert "Brasil x Argentina" in label
    assert "16:00" in label


def test_matchup_str_renders_home_x_away() -> None:
    matchup = Matchup(home_name="Brasil", away_name="Argentina")
    assert str(matchup) == "Brasil x Argentina"
    assert matchup.home_name == "Brasil"
    assert matchup.away_name == "Argentina"
