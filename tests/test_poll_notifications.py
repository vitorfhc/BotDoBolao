"""Pure tests for kickoff/goal detection + pt-BR rendering (COMPLETION.md §9.3)."""

from __future__ import annotations

from datetime import UTC, datetime

from tigrinho.bot.poll_cog import (
    GoalNotice,
    build_goal_notices,
    detect_goal_deltas,
    detect_kickoff,
    render_goal_message,
    render_kickoff_message,
)
from tigrinho.providers.base import GameStatus

NOW = datetime(2026, 6, 15, 18, 0, tzinfo=UTC)


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


def test_build_goal_notices_single_home_goal() -> None:
    notices, new_h, new_a = build_goal_notices(
        fixture_id=1,
        home_team_name="Brasil",
        away_team_name="Argentina",
        stored_home=0,
        stored_away=0,
        current_home=1,
        current_away=0,
    )
    assert (new_h, new_a) == (1, 0)
    assert notices == [GoalNotice(1, "Brasil", "Argentina", 1, 0)]


def test_build_goal_notices_none_stored_is_zero() -> None:
    notices, new_h, new_a = build_goal_notices(
        fixture_id=1,
        home_team_name="Brasil",
        away_team_name="Argentina",
        stored_home=None,
        stored_away=None,
        current_home=1,
        current_away=0,
    )
    assert (new_h, new_a) == (1, 0)
    assert [(n.home_goals, n.away_goals) for n in notices] == [(1, 0)]


def test_build_goal_notices_multi_goal_cycle_running_scoreline() -> None:
    # Both sides scored since the last poll: home goals first, then away, each with the running
    # scoreline (no scorer/minute available in scoreline-only mode).
    notices, new_h, new_a = build_goal_notices(
        fixture_id=1,
        home_team_name="Brasil",
        away_team_name="Argentina",
        stored_home=0,
        stored_away=0,
        current_home=2,
        current_away=1,
    )
    assert (new_h, new_a) == (2, 1)
    assert [(n.home_goals, n.away_goals) for n in notices] == [(1, 0), (2, 0), (2, 1)]


def test_build_goal_notices_var_drop_resyncs_without_notice() -> None:
    notices, new_h, new_a = build_goal_notices(
        fixture_id=1,
        home_team_name="Brasil",
        away_team_name="Argentina",
        stored_home=1,
        stored_away=0,
        current_home=0,
        current_away=0,
    )
    assert notices == []
    assert (new_h, new_a) == (0, 0)


def test_build_goal_notices_var_one_side_plus_goal_other_side() -> None:
    # Home VAR (1 -> 0) while away scores (0 -> 1): away goal still announced; home resyncs.
    notices, new_h, new_a = build_goal_notices(
        fixture_id=1,
        home_team_name="Brasil",
        away_team_name="Argentina",
        stored_home=1,
        stored_away=0,
        current_home=0,
        current_away=1,
    )
    assert (new_h, new_a) == (0, 1)
    assert notices == [GoalNotice(1, "Brasil", "Argentina", 0, 1)]


def test_build_goal_notices_unchanged_is_noop() -> None:
    notices, new_h, new_a = build_goal_notices(
        fixture_id=1,
        home_team_name="Brasil",
        away_team_name="Argentina",
        stored_home=1,
        stored_away=1,
        current_home=1,
        current_away=1,
    )
    assert notices == []
    assert (new_h, new_a) == (1, 1)


def test_render_kickoff_message() -> None:
    msg = render_kickoff_message("Brasil", "Argentina")
    assert msg == "🟢 **Bola rolando!** Brasil x Argentina — as apostas estão encerradas. 🐯"


def test_render_goal_message() -> None:
    msg = render_goal_message(GoalNotice(1, "Brasil", "Argentina", 2, 1))
    assert msg == "⚽ **Gol!** Brasil 2x1 Argentina"
