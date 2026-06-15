"""Pure tests for kickoff/goal detection + pt-BR rendering (COMPLETION.md §9.3)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TypedDict

from tigrinho.bot.poll_cog import (
    GoalAnnouncement,
    detect_goal_deltas,
    detect_kickoff,
    reconcile_goals,
    render_goal_message,
    render_kickoff_message,
)
from tigrinho.providers.base import GameStatus, GoalEvent

NOW = datetime(2026, 6, 15, 18, 0, tzinfo=UTC)


class _ReconcileTeams(TypedDict):
    home_team_id: int
    home_team_name: str
    away_team_name: str


# Home team id 10 ("Brasil"), away team id 20 ("Argentina") in all reconcile tests.
_RECONCILE_TEAMS: _ReconcileTeams = {
    "home_team_id": 10,
    "home_team_name": "Brasil",
    "away_team_name": "Argentina",
}


def test_detect_kickoff_true_when_live_and_unannounced() -> None:
    assert detect_kickoff(status=GameStatus.LIVE, kickoff_announced_at=None) is True


def test_detect_kickoff_false_when_already_announced() -> None:
    assert detect_kickoff(status=GameStatus.LIVE, kickoff_announced_at=NOW) is False


def test_detect_kickoff_false_when_not_live() -> None:
    assert detect_kickoff(status=GameStatus.SCHEDULED, kickoff_announced_at=None) is False
    assert detect_kickoff(status=GameStatus.FINISHED, kickoff_announced_at=None) is False


def test_detect_goal_deltas_counts_new_goals_per_side() -> None:
    delta = detect_goal_deltas(stored_home=0, stored_away=0, current_home=1, current_away=0)
    assert (delta.home_new, delta.away_new) == (1, 0)
    assert delta.has_new is True


def test_detect_goal_deltas_treats_none_stored_as_zero() -> None:
    delta = detect_goal_deltas(stored_home=None, stored_away=None, current_home=2, current_away=1)
    assert (delta.home_new, delta.away_new) == (2, 1)


def test_detect_goal_deltas_ignores_decreases() -> None:
    # VAR disallowed a goal: live score dropped -> no new goals.
    delta = detect_goal_deltas(stored_home=1, stored_away=0, current_home=0, current_away=0)
    assert delta.has_new is False
    assert (delta.home_new, delta.away_new) == (0, 0)


def test_reconcile_goals_single_home_goal_named() -> None:
    timeline = (GoalEvent(23, 10, 7, "Neymar", is_own_goal=False, is_penalty=False),)
    anns, new_h, new_a = reconcile_goals(
        **_RECONCILE_TEAMS,
        stored_home=0,
        stored_away=0,
        current_home=1,
        current_away=0,
        timeline=timeline,
    )
    assert (new_h, new_a) == (1, 0)
    assert len(anns) == 1
    assert anns[0].scoring_team_name == "Brasil"
    assert anns[0].home_goals == 1 and anns[0].away_goals == 0
    assert anns[0].scorer_name == "Neymar" and anns[0].minute == 23
    assert anns[0].is_own_goal is False and anns[0].is_penalty is False


def test_reconcile_goals_own_goal_credits_other_side() -> None:
    # An own goal by an away player (team 20) increases the HOME score.
    timeline = (GoalEvent(30, 20, 99, "Azar", is_own_goal=True, is_penalty=False),)
    anns, new_h, new_a = reconcile_goals(
        **_RECONCILE_TEAMS,
        stored_home=0,
        stored_away=0,
        current_home=1,
        current_away=0,
        timeline=timeline,
    )
    assert (new_h, new_a) == (1, 0)
    assert len(anns) == 1
    assert anns[0].scoring_team_name == "Brasil"  # beneficiary
    assert anns[0].is_own_goal is True


def test_reconcile_goals_penalty_flag() -> None:
    timeline = (GoalEvent(55, 10, 8, "Cobrador", is_own_goal=False, is_penalty=True),)
    anns, _, _ = reconcile_goals(
        **_RECONCILE_TEAMS,
        stored_home=0,
        stored_away=0,
        current_home=1,
        current_away=0,
        timeline=timeline,
    )
    assert anns[0].is_penalty is True


def test_reconcile_goals_var_drop_resyncs_without_announcing() -> None:
    anns, new_h, new_a = reconcile_goals(
        **_RECONCILE_TEAMS,
        stored_home=1,
        stored_away=0,
        current_home=0,
        current_away=0,
        timeline=(),
    )
    assert anns == []
    assert (new_h, new_a) == (0, 0)


def test_reconcile_goals_events_lag_falls_back_to_unnamed() -> None:
    # Live score says 1-0 but the events feed hasn't caught up (empty timeline).
    anns, new_h, new_a = reconcile_goals(
        **_RECONCILE_TEAMS,
        stored_home=0,
        stored_away=0,
        current_home=1,
        current_away=0,
        timeline=(),
    )
    assert (new_h, new_a) == (1, 0)
    assert len(anns) == 1
    assert anns[0].scorer_name is None
    assert anns[0].home_goals == 1 and anns[0].away_goals == 0


def test_reconcile_goals_unchanged_is_noop() -> None:
    anns, new_h, new_a = reconcile_goals(
        **_RECONCILE_TEAMS,
        stored_home=1,
        stored_away=1,
        current_home=1,
        current_away=1,
        timeline=(
            GoalEvent(10, 10, 7, "A", is_own_goal=False, is_penalty=False),
            GoalEvent(20, 20, 8, "B", is_own_goal=False, is_penalty=False),
        ),
    )
    assert anns == []
    assert (new_h, new_a) == (1, 1)


def test_render_kickoff_message() -> None:
    msg = render_kickoff_message("Brasil", "Argentina")
    assert msg == "🟢 **Bola rolando!** Brasil x Argentina — as apostas estão encerradas. 🐯"


def test_render_goal_message_named_scorer() -> None:
    ann = GoalAnnouncement(
        scoring_team_name="Brasil",
        home_team_name="Brasil",
        away_team_name="Argentina",
        home_goals=1,
        away_goals=0,
        scorer_name="Neymar",
        minute=23,
        is_own_goal=False,
        is_penalty=False,
    )
    assert render_goal_message(ann) == (
        "⚽ **GOOOL do Brasil!** Brasil 1x0 Argentina — 👟 Neymar (23')"
    )


def test_render_goal_message_own_goal_and_penalty_annotations() -> None:
    own = GoalAnnouncement(
        scoring_team_name="Brasil",
        home_team_name="Brasil",
        away_team_name="Argentina",
        home_goals=1,
        away_goals=0,
        scorer_name="Azar",
        minute=30,
        is_own_goal=True,
        is_penalty=False,
    )
    assert render_goal_message(own) == (
        "⚽ **GOOOL do Brasil!** Brasil 1x0 Argentina — 👟 Azar (30', gol contra)"
    )
    pen = GoalAnnouncement(
        scoring_team_name="Argentina",
        home_team_name="Brasil",
        away_team_name="Argentina",
        home_goals=1,
        away_goals=1,
        scorer_name="Messi",
        minute=70,
        is_own_goal=False,
        is_penalty=True,
    )
    assert render_goal_message(pen) == (
        "⚽ **GOOOL do Argentina!** Brasil 1x1 Argentina — 👟 Messi (70', de pênalti)"
    )


def test_render_goal_message_unknown_scorer() -> None:
    ann = GoalAnnouncement(
        scoring_team_name="Brasil",
        home_team_name="Brasil",
        away_team_name="Argentina",
        home_goals=1,
        away_goals=0,
        scorer_name=None,
        minute=None,
        is_own_goal=False,
        is_penalty=False,
    )
    assert render_goal_message(ann) == (
        "⚽ **GOOOL do Brasil!** Brasil 1x0 Argentina — 👟 artilheiro a confirmar"
    )


def test_reconcile_goals_interleaved_scorelines_multi_goal_cycle() -> None:
    # Both sides score within one poll cycle: scorelines must reflect the minute order.
    timeline = (
        GoalEvent(10, 10, 7, "A", is_own_goal=False, is_penalty=False),  # home -> 1x0
        GoalEvent(20, 20, 8, "B", is_own_goal=False, is_penalty=False),  # away -> 1x1
        GoalEvent(30, 10, 9, "C", is_own_goal=False, is_penalty=False),  # home -> 2x1
    )
    anns, new_h, new_a = reconcile_goals(
        home_team_id=10,
        home_team_name="Brasil",
        away_team_name="Argentina",
        stored_home=0,
        stored_away=0,
        current_home=2,
        current_away=1,
        timeline=timeline,
    )
    assert (new_h, new_a) == (2, 1)
    assert [(a.home_goals, a.away_goals, a.scorer_name) for a in anns] == [
        (1, 0, "A"),
        (1, 1, "B"),
        (2, 1, "C"),
    ]


def test_reconcile_goals_var_one_side_plus_goal_other_side() -> None:
    # Home had 1 (stored), VAR disallows it (live home 0); away scores (live away 1).
    # The away goal must still be announced; the home side resyncs silently.
    timeline = (GoalEvent(40, 20, 8, "B", is_own_goal=False, is_penalty=False),)
    anns, new_h, new_a = reconcile_goals(
        home_team_id=10,
        home_team_name="Brasil",
        away_team_name="Argentina",
        stored_home=1,
        stored_away=0,
        current_home=0,
        current_away=1,
        timeline=timeline,
    )
    assert (new_h, new_a) == (0, 1)
    assert len(anns) == 1
    assert anns[0].scoring_team_name == "Argentina"
    assert anns[0].home_goals == 0 and anns[0].away_goals == 1
    assert anns[0].scorer_name == "B"


def test_reconcile_goals_timeline_leads_live_caps_at_live_count() -> None:
    # Timeline already lists 2 home goals but the live score shows only 1 -> announce just 1.
    timeline = (
        GoalEvent(10, 10, 7, "A", is_own_goal=False, is_penalty=False),
        GoalEvent(15, 10, 9, "C", is_own_goal=False, is_penalty=False),
    )
    anns, new_h, new_a = reconcile_goals(
        home_team_id=10,
        home_team_name="Brasil",
        away_team_name="Argentina",
        stored_home=0,
        stored_away=0,
        current_home=1,
        current_away=0,
        timeline=timeline,
    )
    assert (new_h, new_a) == (1, 0)
    assert len(anns) == 1
    assert anns[0].scorer_name == "A"  # surplus ignored until the live score catches up
