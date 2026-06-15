"""Edge case for scoring: a knockout with no determined advancing team (COMPLETION.md §8.1)."""

from __future__ import annotations

import pytest

from tigrinho.domain.bets import WinnerPayload, WinnerSelection
from tigrinho.domain.scoring import MatchFacts, is_winning_bet
from tigrinho.providers.base import Stage


def _knockout_facts(advancing: int | None) -> MatchFacts:
    return MatchFacts(
        stage=Stage.KNOCKOUT,
        home_team_id=10,
        away_team_id=20,
        home_goals_90=1,
        away_goals_90=1,
        goals=(),
        advancing_team_id=advancing,
    )


@pytest.mark.parametrize("advancing", [None, 999])  # undetermined, or an id matching no team
def test_knockout_without_advancing_team_loses_every_winner_bet(advancing: int | None) -> None:
    facts = _knockout_facts(advancing)
    for selection in WinnerSelection:
        assert is_winning_bet(WinnerPayload(selection), facts) is False
