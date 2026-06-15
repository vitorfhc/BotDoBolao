# Kickoff & Goal Notifications — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the bot post a Discord message to the announce channel when a match kicks off and on every goal (with scorer + scoreline), no role ping.

**Architecture:** Extend the existing 1-minute `PollCog` poll cycle. The per-cycle date-windowed `/fixtures` call already returns the live score (API `goals.{home,away}`), so goal detection costs zero extra API calls; the scorer timeline (`/fixtures/events`) is fetched only when a score changes. Detection is pure and unit-tested; the cog does the I/O. Dedup state (kickoff-announced flag + last-announced score) is persisted on the `games` row, so restarts never re-announce.

**Tech Stack:** Python 3.12, discord.py (`discord.ext.tasks`), SQLAlchemy 2.0 typed ORM, Alembic, pytest (`mypy --strict`, `ruff`).

**Spec:** `docs/superpowers/specs/2026-06-15-kickoff-goal-notifications-design.md`

**Deviations from spec (intentional):**
1. `providers/fake.py` needs **no** change — `FakeProvider` passes `MatchResult` objects through unchanged, so only test constructors set the new live-score fields.
2. The goal message omits the country-flag emoji shown in the spec mockup — the data layer has no per-team flag/country code, so we render team names only.

**Conventions to follow:**
- Run the full gate after each task: `uv run ruff check . && uv run ruff format --check . && uv run mypy --strict . && uv run pytest -q`
- Pure functions only over value objects (no I/O) for detection/rendering.
- Commit after each task with a `feat:`/`docs:` message.

---

### Task 1: Provider — surface the live score on `MatchResult`

**Files:**
- Modify: `tigrinho/providers/base.py` (the `MatchResult` dataclass, ~lines 64-78)
- Modify: `tigrinho/providers/api_football.py` (`parse_match_result`, ~lines 111-135)
- Test: `tests/test_api_football_mapping.py`

- [ ] **Step 1: Write the failing tests**

Add these two tests to `tests/test_api_football_mapping.py` (after `test_parse_match_result_group_no_advancing`, ~line 142):

```python
def test_parse_match_result_includes_live_score() -> None:
    # The top-level `goals` object is the current/live aggregate score (API `goals.{home,away}`).
    result = parse_match_result(_KNOCKOUT_PENALTIES)
    assert result.home_goals == 1
    assert result.away_goals == 1


def test_parse_match_result_live_score_present_while_fulltime_null() -> None:
    # In-play fixture: `score.fulltime` is null, but `goals` carries the live score.
    item: dict[str, Any] = {
        "fixture": {"id": 2, "date": "2026-06-15T16:00:00-03:00", "status": {"short": "1H"}},
        "league": {"round": "Group A - 1"},
        "teams": {
            "home": {"id": 10, "name": "Brasil"},
            "away": {"id": 20, "name": "Argentina"},
        },
        "goals": {"home": 1, "away": 0},
        "score": {"fulltime": {"home": None, "away": None}},
    }
    result = parse_match_result(item)
    assert result.status is GameStatus.LIVE
    assert result.home_goals_90 is None  # regulation result not final yet
    assert result.away_goals_90 is None
    assert result.home_goals == 1  # live score available
    assert result.away_goals == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_api_football_mapping.py::test_parse_match_result_includes_live_score -v`
Expected: FAIL with `AttributeError: 'MatchResult' object has no attribute 'home_goals'`

- [ ] **Step 3: Add the fields to `MatchResult`**

In `tigrinho/providers/base.py`, replace the `MatchResult` class body docstring + fields (lines 64-78) with:

```python
@dataclass(frozen=True, slots=True)
class MatchResult:
    """Live or final result. ``home_goals_90``/``away_goals_90`` are the **90-minute** regulation
    result (``score.fulltime``), used by settlement (COMPLETION.md §7.2). ``home_goals``/``away_goals``
    are the **current/live aggregate** score (API top-level ``goals`` field), used for goal
    notifications; they default to ``None`` for providers/fixtures that don't supply them.

    ``goals`` is ordered by minute ascending. ``advancing_team_id`` is set only for knockout
    fixtures (the side that progresses, derived from extra time / penalties).
    """

    fixture_id: int
    status: GameStatus
    stage: Stage
    home_goals_90: int | None
    away_goals_90: int | None
    goals: tuple[GoalEvent, ...]
    advancing_team_id: int | None
    home_goals: int | None = None
    away_goals: int | None = None
```

- [ ] **Step 4: Populate the fields in `parse_match_result`**

In `tigrinho/providers/api_football.py`, in `parse_match_result` (after `fulltime = item["score"].get("fulltime") or {}`, line 120), add the live-score lookup and pass the new fields. Replace the function body from line 118 to the `return` with:

```python
    fixture = item["fixture"]
    teams = item["teams"]
    fulltime = item["score"].get("fulltime") or {}
    live = item.get("goals") or {}
    home, away = teams["home"], teams["away"]
    advancing: int | None = None
    if home.get("winner") is True:
        advancing = int(home["id"])
    elif away.get("winner") is True:
        advancing = int(away["id"])
    return MatchResult(
        fixture_id=int(fixture["id"]),
        status=normalize_status(str(fixture["status"]["short"])),
        stage=parse_stage(str(item["league"]["round"])),
        home_goals_90=_opt_int(fulltime.get("home")),
        away_goals_90=_opt_int(fulltime.get("away")),
        goals=goals,
        advancing_team_id=advancing,
        home_goals=_opt_int(live.get("home")),
        away_goals=_opt_int(live.get("away")),
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_api_football_mapping.py -v`
Expected: PASS (all mapping tests, including the two new ones)

- [ ] **Step 6: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy --strict . && uv run pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add tigrinho/providers/base.py tigrinho/providers/api_football.py tests/test_api_football_mapping.py
git commit -m "feat(providers): expose live score (goals.home/away) on MatchResult"
```

---

### Task 2: Schema — `games` dedup columns + migration

**Files:**
- Modify: `tigrinho/db/models.py` (the `Game` class, ~lines 44-66)
- Create: `tigrinho/db/migrations/versions/b7c3f1a9d2e4_kickoff_goal_notification_state.py`
- Test: `tests/test_migrations.py` (existing — drives the loop)

- [ ] **Step 1: Verify the schema test passes BEFORE changes (baseline)**

Run: `uv run pytest tests/test_migrations.py::test_migrated_schema_matches_models -v`
Expected: PASS (model and migrations currently agree)

- [ ] **Step 2: Add the columns to the `Game` model**

In `tigrinho/db/models.py`, in the `Game` class, add three columns immediately after `announced_at` (line 63), before `settled_at`:

```python
    announced_at: Mapped[datetime | None]
    kickoff_announced_at: Mapped[datetime | None]
    last_announced_home_goals: Mapped[int | None]
    last_announced_away_goals: Mapped[int | None]
    settled_at: Mapped[datetime | None]
```

- [ ] **Step 3: Run the schema test to verify it now FAILS**

Run: `uv run pytest tests/test_migrations.py::test_migrated_schema_matches_models -v`
Expected: FAIL — `compare_metadata` reports the three new model columns are missing from the migrated DB (`diffs != []`).

- [ ] **Step 4: Write the migration**

Create `tigrinho/db/migrations/versions/b7c3f1a9d2e4_kickoff_goal_notification_state.py`:

```python
"""kickoff & goal notification state

Revision ID: b7c3f1a9d2e4
Revises: ed421d04f4c4
Create Date: 2026-06-15 15:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c3f1a9d2e4"
down_revision: str | Sequence[str] | None = "ed421d04f4c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("games", sa.Column("kickoff_announced_at", sa.DateTime(), nullable=True))
    op.add_column("games", sa.Column("last_announced_home_goals", sa.Integer(), nullable=True))
    op.add_column("games", sa.Column("last_announced_away_goals", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("games", "last_announced_away_goals")
    op.drop_column("games", "last_announced_home_goals")
    op.drop_column("games", "kickoff_announced_at")
```

- [ ] **Step 5: Run the migration tests to verify they pass**

Run: `uv run pytest tests/test_migrations.py -v`
Expected: PASS (`test_migrated_schema_matches_models` now sees `diffs == []`; upgrade/downgrade tests pass)

- [ ] **Step 6: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy --strict . && uv run pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add tigrinho/db/models.py tigrinho/db/migrations/versions/b7c3f1a9d2e4_kickoff_goal_notification_state.py
git commit -m "feat(db): add kickoff/goal notification dedup columns + migration"
```

---

### Task 3: Pure detection + rendering helpers

All pure (no I/O), in `poll_cog.py` alongside the existing pure helpers (`render_results_message`, `should_poll`).

**Files:**
- Modify: `tigrinho/bot/poll_cog.py` (add value objects + pure functions; add `GoalEvent` to the `providers.base` import on line 26)
- Test: `tests/test_poll_notifications.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_poll_notifications.py`:

```python
"""Pure tests for kickoff/goal detection + pt-BR rendering (COMPLETION.md §9.3)."""

from __future__ import annotations

from datetime import UTC, datetime

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

# Home team id 10 ("Brasil"), away team id 20 ("Argentina") in all reconcile tests.
_RECONCILE_TEAMS = {
    "home_team_id": 10,
    "away_team_id": 20,
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_poll_notifications.py -v`
Expected: FAIL with `ImportError: cannot import name 'GoalAnnouncement' from 'tigrinho.bot.poll_cog'`

- [ ] **Step 3: Add `GoalEvent` to the imports**

In `tigrinho/bot/poll_cog.py`, update the `providers.base` import (line 26) to include `GoalEvent`:

```python
from tigrinho.providers.base import FootballProvider, GameStatus, GoalEvent, MatchResult
```

- [ ] **Step 4: Add the value objects + pure functions**

In `tigrinho/bot/poll_cog.py`, after the `SettledGame` dataclass (line 58) and before `apply_settlement` (line 60), insert:

```python
@dataclass(frozen=True, slots=True)
class KickoffNotice:
    """A game that just kicked off (bets now closed)."""

    fixture_id: int
    home_team_name: str
    away_team_name: str


@dataclass(frozen=True, slots=True)
class GoalAnnouncement:
    """One goal to announce: the beneficiary side, the resulting scoreline, and (best-effort) the
    scorer. ``scorer_name``/``minute`` are ``None`` when the events feed hasn't caught up yet."""

    scoring_team_name: str
    home_team_name: str
    away_team_name: str
    home_goals: int
    away_goals: int
    scorer_name: str | None
    minute: int | None
    is_own_goal: bool
    is_penalty: bool


@dataclass(frozen=True, slots=True)
class GoalNotice:
    """A goal to post for a game."""

    fixture_id: int
    announcement: GoalAnnouncement


@dataclass(frozen=True, slots=True)
class GoalDelta:
    """How many new goals appeared this cycle, per side (from the live-score diff)."""

    home_new: int
    away_new: int

    @property
    def has_new(self) -> bool:
        return self.home_new > 0 or self.away_new > 0


@dataclass(frozen=True, slots=True)
class PollOutcome:
    """Everything one poll cycle produced: settlements + live-match notifications (§9.2/§9.3)."""

    settled: list[SettledGame]
    kickoffs: list[KickoffNotice]
    goals: list[GoalNotice]


def detect_kickoff(*, status: GameStatus, kickoff_announced_at: datetime | None) -> bool:
    """A kickoff is announceable when the game is LIVE and we haven't announced it yet."""
    return status is GameStatus.LIVE and kickoff_announced_at is None


def detect_goal_deltas(
    *,
    stored_home: int | None,
    stored_away: int | None,
    current_home: int | None,
    current_away: int | None,
) -> GoalDelta:
    """New goals per side since the last announced score. Decreases (VAR) yield zero — the caller
    resyncs the stored score down without announcing. ``None`` is treated as 0."""
    sh = stored_home or 0
    sa_ = stored_away or 0
    ch = current_home or 0
    ca = current_away or 0
    return GoalDelta(home_new=max(0, ch - sh), away_new=max(0, ca - sa_))


def reconcile_goals(
    *,
    home_team_id: int,
    away_team_id: int,
    home_team_name: str,
    away_team_name: str,
    stored_home: int | None,
    stored_away: int | None,
    current_home: int | None,
    current_away: int | None,
    timeline: tuple[GoalEvent, ...],
) -> tuple[list[GoalAnnouncement], int, int]:
    """Turn a live-score change into per-goal announcements, returning
    ``(announcements, new_stored_home, new_stored_away)``.

    The **live score** (``current_home``/``current_away``) is the source of truth for *how many*
    goals exist; the ``timeline`` (from ``/fixtures/events``) names the scorers. Own goals count for
    the opponent. If the timeline lags (fewer entries than the live score), the extra goals are
    announced with ``scorer_name=None`` ('artilheiro a confirmar'). A decrease (VAR) produces no
    announcements and just resyncs the stored score. ``None`` live scores leave that side unchanged.
    """
    sh = stored_home or 0
    sa_ = stored_away or 0
    ch = current_home if current_home is not None else sh
    ca = current_away if current_away is not None else sa_

    # VAR / disallowed goal: a side dropped -> resync to live, announce nothing.
    if ch < sh or ca < sa_:
        return ([], ch, ca)

    # Split the timeline into beneficiary-ordered goal lists (own goals credit the opponent).
    home_events: list[GoalEvent] = []
    away_events: list[GoalEvent] = []
    for event in timeline:
        scored_by_home = event.team_id == home_team_id
        home_benefits = (not scored_by_home) if event.is_own_goal else scored_by_home
        (home_events if home_benefits else away_events).append(event)

    announcements: list[GoalAnnouncement] = []
    for index in range(sh, ch):  # new home goals: stored_home .. current_home - 1
        event = home_events[index] if index < len(home_events) else None
        announcements.append(
            GoalAnnouncement(
                scoring_team_name=home_team_name,
                home_team_name=home_team_name,
                away_team_name=away_team_name,
                home_goals=index + 1,
                away_goals=ca,
                scorer_name=event.player_name if event is not None else None,
                minute=event.minute if event is not None else None,
                is_own_goal=event.is_own_goal if event is not None else False,
                is_penalty=event.is_penalty if event is not None else False,
            )
        )
    for index in range(sa_, ca):  # new away goals
        event = away_events[index] if index < len(away_events) else None
        announcements.append(
            GoalAnnouncement(
                scoring_team_name=away_team_name,
                home_team_name=home_team_name,
                away_team_name=away_team_name,
                home_goals=ch,
                away_goals=index + 1,
                scorer_name=event.player_name if event is not None else None,
                minute=event.minute if event is not None else None,
                is_own_goal=event.is_own_goal if event is not None else False,
                is_penalty=event.is_penalty if event is not None else False,
            )
        )
    return (announcements, ch, ca)


def render_kickoff_message(home_team_name: str, away_team_name: str) -> str:
    """pt-BR kickoff message (bets are now closed)."""
    return f"🟢 **Bola rolando!** {home_team_name} x {away_team_name} — as apostas estão encerradas. 🐯"


def render_goal_message(announcement: GoalAnnouncement) -> str:
    """pt-BR goal message: beneficiary team, scoreline, and best-effort scorer with annotations."""
    scoreline = (
        f"{announcement.home_team_name} {announcement.home_goals}x{announcement.away_goals} "
        f"{announcement.away_team_name}"
    )
    head = f"⚽ **GOOOL do {announcement.scoring_team_name}!** {scoreline}"
    if announcement.scorer_name is None:
        return f"{head} — 👟 artilheiro a confirmar"
    extras: list[str] = []
    if announcement.minute is not None:
        extras.append(f"{announcement.minute}'")
    if announcement.is_own_goal:
        extras.append("gol contra")
    if announcement.is_penalty:
        extras.append("de pênalti")
    suffix = f" ({', '.join(extras)})" if extras else ""
    return f"{head} — 👟 {announcement.scorer_name}{suffix}"
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_poll_notifications.py -v`
Expected: PASS (all 16 tests)

- [ ] **Step 6: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy --strict . && uv run pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add tigrinho/bot/poll_cog.py tests/test_poll_notifications.py
git commit -m "feat(poll): pure kickoff/goal detection + pt-BR renderers"
```

---

### Task 4: Orchestrator — `collect_settlements` → `collect_poll_outcome`

Rename `collect_settlements` to `collect_poll_outcome` and extend it to also emit kickoff + goal notices from the same single date-windowed call. Update all call sites.

**Files:**
- Modify: `tigrinho/bot/poll_cog.py` (`collect_settlements` → `collect_poll_outcome`, lines 140-172; and its caller in `run_poll`, line 265)
- Modify: `tests/test_poll_collect.py` (import + 4 calls + the live-game test)
- Modify: `tests/test_e2e_fake.py` (import line 18, call line 120, assert line 122)
- Modify: `tests/test_budget_e2e.py` (import line 13, call line 87)

- [ ] **Step 1: Rewrite the function**

In `tigrinho/bot/poll_cog.py`, replace the entire `collect_settlements` function (lines 140-172) with:

```python
async def collect_poll_outcome(
    session: Session, provider: FootballProvider, settings: Settings, *, now: datetime
) -> PollOutcome:
    """Run one poll pass over every pollable game and return its outcome (COMPLETION.md §9.2/§9.3).

    One date-windowed call fetches current status + live score for all games. For each game we:
    - settle it if now FINISHED (fetching the goal timeline once);
    - else, while LIVE, announce the kickoff once and any new goals (the live-score diff is the
      trigger; the goal timeline — fetched only when the score changes — names the scorer).

    Self-healing settlement is unchanged. Dedup state is persisted on the game row, so this is
    idempotent across restarts. May raise ``BudgetExceeded`` (the cog turns it into a skip). No
    commit — the caller commits.
    """
    games = GameRepository(session)
    pollable = games.list_active(now, settings.settle_grace_hours)
    if not pollable:
        return PollOutcome(settled=[], kickoffs=[], goals=[])
    results = {
        result.fixture_id: result
        for result in await provider.get_recent_results(settings.settle_grace_hours)
    }
    settled: list[SettledGame] = []
    kickoffs: list[KickoffNotice] = []
    goal_notices: list[GoalNotice] = []
    for game in pollable:
        result = results.get(game.fixture_id)
        if result is None:
            continue
        game.status = result.status.value
        if result.status is GameStatus.FINISHED:
            full_result = await provider.get_match_result(game.fixture_id)
            outcome = apply_settlement(session, full_result, now=now)
            if outcome is not None:
                settled.append(outcome)
            continue
        if result.status is GameStatus.LIVE:
            if detect_kickoff(status=result.status, kickoff_announced_at=game.kickoff_announced_at):
                game.kickoff_announced_at = now
                kickoffs.append(
                    KickoffNotice(game.fixture_id, game.home_team_name, game.away_team_name)
                )
            if result.home_goals is not None or result.away_goals is not None:
                delta = detect_goal_deltas(
                    stored_home=game.last_announced_home_goals,
                    stored_away=game.last_announced_away_goals,
                    current_home=result.home_goals,
                    current_away=result.away_goals,
                )
                timeline: tuple[GoalEvent, ...] = ()
                if delta.has_new:
                    timeline = (await provider.get_match_result(game.fixture_id)).goals
                announcements, new_home, new_away = reconcile_goals(
                    home_team_id=game.home_team_id,
                    home_team_name=game.home_team_name,
                    away_team_name=game.away_team_name,
                    stored_home=game.last_announced_home_goals,
                    stored_away=game.last_announced_away_goals,
                    current_home=result.home_goals,
                    current_away=result.away_goals,
                    timeline=timeline,
                )
                game.last_announced_home_goals = new_home
                game.last_announced_away_goals = new_away
                goal_notices.extend(
                    GoalNotice(game.fixture_id, announcement) for announcement in announcements
                )
    session.flush()
    return PollOutcome(settled=settled, kickoffs=kickoffs, goals=goal_notices)
```

- [ ] **Step 2: Update the caller in `run_poll`**

In `tigrinho/bot/poll_cog.py`, in `run_poll` (line 265), the call is updated as part of Task 5. For now, to keep the module importable/compiling, change line 265 from:

```python
                settled = await collect_settlements(session, provider, self.settings, now=now)
```

to:

```python
                outcome = await collect_poll_outcome(session, provider, self.settings, now=now)
                settled = outcome.settled
```

(Task 5 rewrites `run_poll` fully to also post the kickoff/goal messages; this minimal edit keeps it green between tasks.)

- [ ] **Step 3: Update `tests/test_e2e_fake.py`**

Line 18 — change the import:

```python
from tigrinho.bot.poll_cog import collect_poll_outcome
```

Lines 119-122 — change the call + assertion:

```python
    with factory() as session:
        outcome = await collect_poll_outcome(session, provider, settings, now=T_SETTLE)
        session.commit()
    assert len(outcome.settled) == 1
```

- [ ] **Step 4: Update `tests/test_budget_e2e.py`**

Line 13 — change the import:

```python
from tigrinho.bot.poll_cog import collect_poll_outcome
```

Line 87 — change the call:

```python
            await collect_poll_outcome(session, provider, _settings(), now=NOW)
```

- [ ] **Step 5: Update `tests/test_poll_collect.py` (import + existing calls)**

Line 12 — change the import:

```python
from tigrinho.bot.poll_cog import collect_poll_outcome, should_poll
```

Line 111 (in `test_collect_no_pollable_games_makes_no_api_call`):

```python
    outcome = await collect_poll_outcome(session, _ExplodingProvider(), _settings(), now=NOW)
    assert outcome.settled == []
```

Lines 133-136 (in `test_collect_self_heals_overdue_game_within_grace`):

```python
    outcome = await collect_poll_outcome(session, provider, _settings(), now=NOW)
    assert len(outcome.settled) == 1  # self-healed despite being past the match window
    game = GameRepository(session).get(1)
    assert game is not None and game.status == "FINISHED"
```

Lines 155-159 (in `test_collect_settles_finished_active_game`):

```python
    outcome = await collect_poll_outcome(session, provider, _settings(), now=NOW)
    assert len(outcome.settled) == 1
    assert outcome.settled[0].players[0].total_points == 2  # WINNER HOME correct
    game = GameRepository(session).get(1)
    assert game is not None and game.status == "FINISHED" and game.first_scorer_player_id == 7
```

- [ ] **Step 6: Update the live-game test (its behavior intentionally changes)**

In `tests/test_poll_collect.py`, replace `test_collect_live_game_updates_status_without_settling` (lines 162-168) with a version that asserts the new kickoff behavior. A freshly-`LIVE` game (with `kickoff_announced_at` unset) now also produces a kickoff notice:

```python
async def test_collect_live_game_announces_kickoff_without_settling(session: Session) -> None:
    _add_game(session, 1, kickoff=NOW - timedelta(hours=1), settled=None)  # active, LIVE
    provider = FakeProvider(recent_results=[_result(GameStatus.LIVE)])
    outcome = await collect_poll_outcome(session, provider, _settings(), now=NOW)
    assert outcome.settled == []
    assert [k.fixture_id for k in outcome.kickoffs] == [1]
    assert outcome.goals == []
    game = GameRepository(session).get(1)
    assert game is not None
    assert game.status == "LIVE" and game.settled_at is None
    assert game.kickoff_announced_at == NOW  # dedup flag set


async def test_collect_kickoff_announced_once(session: Session) -> None:
    # Second poll of an already-announced live game must NOT re-announce the kickoff.
    _add_game(session, 1, kickoff=NOW - timedelta(hours=1), settled=None)
    provider = FakeProvider(recent_results=[_result(GameStatus.LIVE)])
    await collect_poll_outcome(session, provider, _settings(), now=NOW)
    second = await collect_poll_outcome(session, provider, _settings(), now=NOW)
    assert second.kickoffs == []
```

- [ ] **Step 7: Add a goal-detection integration test (with restart idempotency)**

Append to `tests/test_poll_collect.py` a helper and tests that drive goal detection through the DB + a `FakeProvider`. Add this `_live_result` helper near `_result` (after line 83):

```python
def _live_result(
    status: GameStatus, home: int, away: int, *, goals: tuple[GoalEvent, ...] = ()
) -> MatchResult:
    """A MatchResult carrying a live aggregate score (and optional timeline)."""
    return MatchResult(
        fixture_id=1,
        status=status,
        stage=Stage.GROUP,
        home_goals_90=None,
        away_goals_90=None,
        goals=goals,
        advancing_team_id=None,
        home_goals=home,
        away_goals=away,
    )
```

Then append these tests:

```python
async def test_collect_announces_new_goal_with_scorer(session: Session) -> None:
    _add_game(session, 1, kickoff=NOW - timedelta(hours=1), settled=None)
    # Kickoff already announced so this cycle only surfaces the goal.
    game = GameRepository(session).get(1)
    assert game is not None
    game.kickoff_announced_at = NOW
    session.flush()
    goal = GoalEvent(23, 10, 7, "Neymar", is_own_goal=False, is_penalty=False)
    provider = FakeProvider(
        recent_results=[_live_result(GameStatus.LIVE, 1, 0)],
        match_results=[_live_result(GameStatus.LIVE, 1, 0, goals=(goal,))],
    )
    outcome = await collect_poll_outcome(session, provider, _settings(), now=NOW)
    assert len(outcome.goals) == 1
    ann = outcome.goals[0].announcement
    assert ann.scoring_team_name == "Brasil" and ann.scorer_name == "Neymar"
    assert ann.home_goals == 1 and ann.away_goals == 0
    refreshed = GameRepository(session).get(1)
    assert refreshed is not None
    assert refreshed.last_announced_home_goals == 1 and refreshed.last_announced_away_goals == 0


async def test_collect_goal_announced_once_across_restart(session: Session) -> None:
    _add_game(session, 1, kickoff=NOW - timedelta(hours=1), settled=None)
    game = GameRepository(session).get(1)
    assert game is not None
    game.kickoff_announced_at = NOW
    session.flush()
    goal = GoalEvent(23, 10, 7, "Neymar", is_own_goal=False, is_penalty=False)
    provider = FakeProvider(
        recent_results=[_live_result(GameStatus.LIVE, 1, 0)],
        match_results=[_live_result(GameStatus.LIVE, 1, 0, goals=(goal,))],
    )
    first = await collect_poll_outcome(session, provider, _settings(), now=NOW)
    assert len(first.goals) == 1
    # Same live score next cycle (e.g. after a restart): the persisted counter prevents a re-announce.
    second = await collect_poll_outcome(session, provider, _settings(), now=NOW)
    assert second.goals == []
```

- [ ] **Step 8: Run the affected tests to verify they pass**

Run: `uv run pytest tests/test_poll_collect.py tests/test_e2e_fake.py tests/test_budget_e2e.py -v`
Expected: PASS

- [ ] **Step 9: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy --strict . && uv run pytest -q`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add tigrinho/bot/poll_cog.py tests/test_poll_collect.py tests/test_e2e_fake.py tests/test_budget_e2e.py
git commit -m "feat(poll): collect_poll_outcome — emit kickoff + goal notices in the poll pass"
```

---

### Task 5: Wire posting into `PollCog.run_poll` (no role ping)

**Files:**
- Modify: `tigrinho/bot/poll_cog.py` (`run_poll`, `_post_results`; add `_get_announce_channel`, `_post_plain`)
- Test: `tests/test_poll_cog.py` (add a posting test with a stub channel)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_poll_cog.py`:

```python
async def test_post_plain_sends_without_pings(tmp_path: Path) -> None:
    import discord

    from tigrinho.bot.client import TigrinhoBot

    sent: list[tuple[str, discord.AllowedMentions]] = []

    class _StubChannel:
        async def send(
            self, content: str, *, allowed_mentions: discord.AllowedMentions
        ) -> None:
            sent.append((content, allowed_mentions))

    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    bot = TigrinhoBot(_settings())
    try:
        cog = PollCog(
            bot,
            settings=_settings(),
            session_factory=create_session_factory(engine),
            provider_factory=lambda _session: FakeProvider(),
            clock=lambda: NOW,
        )
        # discord.abc.Messageable check is structural enough for get_channel's return here.
        bot.get_channel = lambda _id: _StubChannel()  # type: ignore[method-assign,assignment,return-value]
        await cog._post_plain(["🟢 oi", "⚽ gol"])
    finally:
        await bot.close()

    assert [content for content, _ in sent] == ["🟢 oi", "⚽ gol"]
    assert all(am.roles is False and am.users is False and am.everyone is False for _, am in sent)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_poll_cog.py::test_post_plain_sends_without_pings -v`
Expected: FAIL with `AttributeError: 'PollCog' object has no attribute '_post_plain'`

- [ ] **Step 3: Add the channel helper + plain sender, and rewrite `run_poll`**

In `tigrinho/bot/poll_cog.py`, replace `run_poll` and `_post_results` (lines 248-291) with:

```python
    async def run_poll(self) -> None:
        """One poll cycle: settle finished games, announce kickoffs and goals for live games
        (throttling rechecks of overdue ones), and alert the admin about games that outlived the
        settlement grace (§9.2/§9.3)."""
        now = self._clock()
        with self.session_factory() as session:
            games = GameRepository(session)
            pollable = games.list_active(now, self.settings.settle_grace_hours)
            outcome = PollOutcome(settled=[], kickoffs=[], goals=[])
            if should_poll(
                pollable_kickoffs=[game.kickoff_utc for game in pollable],
                now=now,
                last_poll=self._last_poll,
                match_window_hours=self.settings.match_window_hours,
                stuck_recheck_minutes=self.settings.stuck_recheck_minutes,
            ):
                self._last_poll = now
                provider = self.provider_factory(session)
                outcome = await collect_poll_outcome(session, provider, self.settings, now=now)
            results = [
                (game, resolve_scorer_name(session, game.first_scorer_player_id))
                for game in outcome.settled
            ]
            live_messages = [
                render_kickoff_message(kickoff.home_team_name, kickoff.away_team_name)
                for kickoff in outcome.kickoffs
            ] + [render_goal_message(goal.announcement) for goal in outcome.goals]
            stuck = [
                (game.fixture_id, f"{game.home_team_name} x {game.away_team_name}")
                for game in games.list_stuck(now, self.settings.settle_grace_hours)
            ]
            session.commit()
        await self._post_plain(live_messages)
        await self._post_results(results)
        await self._alert_stuck(stuck)

    def _get_announce_channel(self) -> discord.abc.Messageable | None:
        channel = self.bot.get_channel(self.settings.announce_channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            log.warning(
                "announce_channel_unavailable", channel_id=self.settings.announce_channel_id
            )
            return None
        return channel

    async def _post_plain(self, messages: list[str]) -> None:
        """Post kickoff/goal messages to the announce channel with no pings."""
        if not messages:
            return
        channel = self._get_announce_channel()
        if channel is None:
            return
        for message in messages:
            await channel.send(message, allowed_mentions=discord.AllowedMentions.none())

    async def _post_results(self, results: list[tuple[SettledGame, str | None]]) -> None:
        if not results:
            return
        channel = self._get_announce_channel()
        if channel is None:
            return
        allowed = discord.AllowedMentions(users=True)
        for settled, scorer_name in results:
            await channel.send(
                render_results_message(settled, scorer_name=scorer_name), allowed_mentions=allowed
            )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_poll_cog.py -v`
Expected: PASS

- [ ] **Step 5: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy --strict . && uv run pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tigrinho/bot/poll_cog.py tests/test_poll_cog.py
git commit -m "feat(poll): post kickoff + goal messages to the announce channel (no ping)"
```

---

### Task 6: Docs — `COMPLETION.md` + `/ajuda`

**Files:**
- Modify: `COMPLETION.md` (§7.2 note + new §9.3)
- Modify: `tigrinho/domain/text_pt.py` (`help_text` intro)
- Test: `tests/test_text_pt.py` (run to confirm no regression)

- [ ] **Step 1: Update `COMPLETION.md` §9.2 → add a §9.3**

In `COMPLETION.md`, immediately after the §9.2 "Self-heal & stuck safeguard" paragraph (line 411), insert:

```markdown

### 9.3 Live notifications (kickoff & goals)

The same per-cycle poll also posts live-match notifications to `announce_channel_id` (**no role
ping**):

1. **Kickoff** — when a game's status first becomes `LIVE`, the bot posts a "bola rolando" message
   (bets are now closed) exactly once (deduped via `games.kickoff_announced_at`).
2. **Goals** — the date-windowed `/fixtures` call also returns the **live score** (top-level
   `goals.{home,away}`), so a goal is detected for **free** by comparing it to the last-announced
   score (`games.last_announced_home_goals`/`away`). Only when the score changes does the bot fetch
   `get_match_result()` once to name the scorer. Own goals are credited to the opponent; penalties
   and own goals are annotated. A disallowed goal (VAR, score drops) resyncs silently. If the events
   feed lags, the goal is posted as "artilheiro a confirmar". Penalty-shootout kicks are **not**
   goals (the live `goals` field is match goals only).

Both are restart-safe and idempotent (dedup state persists on the game row).
```

- [ ] **Step 2: Update `COMPLETION.md` §7.2 interface note**

In `COMPLETION.md` §7.2 (the API-Football mapping section), add a bullet noting the live-score
fields. Find the §7.2 area (around line 258-286) and append to its field list:

```markdown
- `MatchResult.home_goals`/`away_goals` — the **current/live aggregate** score (API top-level
  `goals.{home,away}`), used for goal notifications (§9.3); distinct from `home_goals_90`/
  `away_goals_90` (regulation `score.fulltime`, used by settlement).
```

- [ ] **Step 3: Update the `/ajuda` intro text**

In `tigrinho/domain/text_pt.py`, in `help_text` (lines 136-145), extend the second intro paragraph
(line 140-142) to mention the live announcements. Replace that list element with:

```python
        "Qualquer pessoa do servidor pode apostar. Quando um jogo é anunciado, use **/apostar** "
        "para dar seu palpite. As apostas **fecham no apito inicial** de cada jogo. O bot avisa "
        "no canal quando a bola rola e a cada gol; quando o jogo acaba, ele apura tudo sozinho e "
        "atualiza o placar.",
```

- [ ] **Step 4: Run the docs/text tests**

Run: `uv run pytest tests/test_text_pt.py tests/test_claude_md.py tests/test_readme.py -v`
Expected: PASS

- [ ] **Step 5: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy --strict . && uv run pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add COMPLETION.md tigrinho/domain/text_pt.py
git commit -m "docs: COMPLETION §9.3 + /ajuda — kickoff & goal notifications"
```

---

### Task 7: Final verification

- [ ] **Step 1: Full quality gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy --strict . && uv run pytest -q`
Expected: PASS (all tests green, mypy clean, ruff clean)

- [ ] **Step 2: Confirm the migration applies cleanly from scratch**

Run: `uv run pytest tests/test_migrations.py -v`
Expected: PASS (`upgrade head` builds a schema matching the models; downgrade works)

- [ ] **Step 3: Sanity-check the feature surface**

Confirm by inspection that:
- `collect_poll_outcome` is the only orchestrator (no stale `collect_settlements` references): `grep -rn "collect_settlements" tigrinho tests` returns nothing.
- Kickoff/goal messages post with `AllowedMentions.none()` (no ping); results still ping bettors.

---

## Self-Review (completed during planning)

**Spec coverage:**
- Kickoff notification → Tasks 3 (detect/render), 4 (emit), 5 (post). ✓
- Goal notification w/ scorer → Tasks 1 (live score), 3 (reconcile/render), 4 (emit + timeline fetch), 5 (post). ✓
- Zero extra API calls for detection; events fetched only on change → Task 4 (`if delta.has_new`). ✓
- No role ping → Task 5 (`AllowedMentions.none()`). ✓
- Restart-safe dedup → Task 2 (columns), Task 4 (persist + restart test). ✓
- Edge cases (VAR drop, events lag, own goal, penalty, shootout-excluded) → Task 3 tests + reconcile logic. ✓
- Docs (COMPLETION + /ajuda) → Task 6. ✓

**Placeholder scan:** none — every code step contains full content.

**Type consistency:** `PollOutcome{settled,kickoffs,goals}`, `KickoffNotice{fixture_id,home_team_name,away_team_name}`, `GoalNotice{fixture_id,announcement}`, `GoalAnnouncement{...}`, `GoalDelta{home_new,away_new,has_new}` used consistently across Tasks 3–5. `collect_poll_outcome` signature identical at all call sites. `reconcile_goals` returns `(list[GoalAnnouncement], int, int)` everywhere.
