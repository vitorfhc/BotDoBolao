"""Pure helpers for the /apostar component flow (COMPLETION.md §8.1, §8.2).

These hold the logic that must be correct and is easy to get wrong — the knockout "hide DRAW"
rule and Discord's 25-option Select limit (squad pagination) — so they are unit-tested. The
``ui.View``/``Select``/``Modal`` glue is layered on top.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from tigrinho.domain.bets import WinnerSelection
from tigrinho.providers.base import Stage

from .sync_planning import format_kickoff_pt

# A Discord Select may show at most 25 options (so long squads must be paginated).
DISCORD_SELECT_LIMIT = 25


def winner_selection_options(stage: Stage) -> list[WinnerSelection]:
    """Winner choices to offer; knockout hides DRAW (a knockout is never a draw — §8.1)."""
    if stage is Stage.KNOCKOUT:
        return [WinnerSelection.HOME, WinnerSelection.AWAY]
    return [WinnerSelection.HOME, WinnerSelection.DRAW, WinnerSelection.AWAY]


def paginate[T](items: Sequence[T], page_size: int = DISCORD_SELECT_LIMIT) -> list[list[T]]:
    """Split items into pages of <= ``page_size`` (always at least one, possibly empty, page)."""
    pages = [list(items[i : i + page_size]) for i in range(0, len(items), page_size)]
    return pages or [[]]


def game_choice_label(home_name: str, away_name: str, kickoff_local: datetime) -> str:
    """Label for an open-game Select option, e.g. ``Brasil x Argentina — Sáb 16/06 16:00``."""
    return f"{home_name} x {away_name} — {format_kickoff_pt(kickoff_local)}"
