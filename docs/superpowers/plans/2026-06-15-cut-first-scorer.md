# Cut FIRST_SCORER + Squad Infrastructure — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fully remove the `FIRST_SCORER` bet category and everything that existed only to support it (squad rosters + API sync + cache table, and the per-goal timeline), leaving a 4-category bot.

**Architecture:** Remove in dependency order so the full quality gate stays green at every commit: (1) bot/CLI UI leaves that consume first-scorer, (2) the FIRST_SCORER domain category, (3) the now-orphaned goal timeline, (4) squad infrastructure (provider VO + Protocol method, ORM model + column, repository, CLI command), (5) a forward Alembic migration that drops the column/table and purges FIRST_SCORER bets, (6) docs. `mypy --strict` exhaustiveness on `match` statements mechanically flags any missed arm.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0 + Alembic (SQLite, `render_as_batch=True`), discord.py, Typer, httpx, pytest, ruff, mypy.

**Quality gate (run after every task before committing):**
```
uv run ruff check . && uv run ruff format --check . && uv run mypy --strict . && uv run pytest -q
```

**Baseline:** 324 tests pass on branch `worktree-cut-first-scorer`.

---

### Task 1: Remove the first-scorer betting UI and result display (bot leaves)

These are the outermost consumers. The `FIRST_SCORER` category, `POINTS` entry, goal timeline, squad model/column, and `SquadRepository` all still exist after this task, so the suite stays green.

**Files:**
- Modify: `tigrinho/bot/apostar_view.py`
- Modify: `tigrinho/bot/bets_cog.py`
- Modify: `tigrinho/bot/poll_cog.py`
- Test (delete): `tests/test_apostar_scorer.py`
- Test (modify): `tests/test_apostar_flow.py`, `tests/test_apostar_delete.py`, `tests/test_bets_cog.py`, `tests/test_poll_cog.py`

- [ ] **Step 1 — `apostar_view.py`:** Remove `BetCategory.FIRST_SCORER` from `APOSTAR_CATEGORIES`; delete `ScorerChoice`, `load_scorer_choices`, `ScorerSelect`, `PageButton`, `build_squad_view`; delete the `FIRST_SCORER` branch in `CategorySelect.callback` (the `load_scorer_choices` / "elenco ainda não foi cadastrado" / `build_squad_view` path); remove the `SquadRepository` import and the module docstring mention of "FIRST_SCORER's paginated squad select".
- [ ] **Step 2 — `bets_cog.py`:** Remove the `FirstScorerPayload` and `SquadRepository` imports; delete the `isinstance(payload, FirstScorerPayload)` scorer-name resolution in `build_my_bet_lines` and the `resolver` lambda in `/minhas_apostas`. Bet lines render via `render_payload` without `scorer_name`.
- [ ] **Step 3 — `poll_cog.py`:** Remove the `first_genuine_scorer` import and the `SquadRepository` import; remove `SettledGame.first_scorer_player_id`; remove the `first_scorer = first_genuine_scorer(result.goals)` line and `game.first_scorer_player_id = first_scorer` write; remove `resolve_scorer_name` and the first-scorer line in `render_results_message`. (Leave `result.goals` itself — removed in Task 3.)
- [ ] **Step 4 — Tests:** Delete `tests/test_apostar_scorer.py`. In `test_apostar_flow.py` / `test_apostar_delete.py` remove any FIRST_SCORER selection paths. In `test_bets_cog.py` remove scorer-name resolver assertions. In `test_poll_cog.py` remove `first_scorer_player_id` / scorer-display assertions.
- [ ] **Step 5 — Gate:** `uv run ruff check . && uv run ruff format --check . && uv run mypy --strict . && uv run pytest -q` → all green.
- [ ] **Step 6 — Commit:** `git commit -am "refactor: remove first-scorer betting UI + result display"`

---

### Task 2: Remove the FIRST_SCORER domain category

**Files:**
- Modify: `tigrinho/domain/bets.py`, `tigrinho/domain/scoring.py`, `tigrinho/domain/text_pt.py`
- Test (modify): `tests/test_bets.py`, `tests/test_scoring.py`, `tests/test_render_payload.py`, `tests/test_settlement.py`, `tests/test_settlement_apply.py`, `tests/test_board.py`, `tests/test_board_cog.py`

- [ ] **Step 1 — `bets.py`:** Remove the `FIRST_SCORER` enum member; delete `FirstScorerPayload`; remove it from the `BetPayload` union; remove the `case BetCategory.FIRST_SCORER:` arm in `parse_payload` and the `case FirstScorerPayload(...)` arm in `payload_to_dict`.
- [ ] **Step 2 — `scoring.py`:** Remove `BetCategory.FIRST_SCORER: 4` from `POINTS`; remove the `FirstScorerPayload` import; remove the `case FirstScorerPayload(...)` arm in `is_winning_bet`. (Leave `first_genuine_scorer` + `MatchFacts.goals` for Task 3.)
- [ ] **Step 3 — `text_pt.py`:** Remove the `FirstScorerPayload` import; remove the `case FirstScorerPayload(...)` arm and the `scorer_name` parameter from `render_payload`; remove the `FIRST_SCORER` entries from `CATEGORY_LABELS_PT`, `_CATEGORY_EXAMPLES_PT`, `_CATEGORY_ORDER`; remove the two first-scorer rule bullets in `help_text()` (the "primeiro a marcar" mentions in the placar-rule bullet and the dedicated own-goal/0x0 bullet).
- [ ] **Step 4 — Tests:** Remove FIRST_SCORER parse/serialize cases (`test_bets.py`), the `first_scorer` grading + `POINTS[FIRST_SCORER]==4` assertions (`test_scoring.py`), the scorer render + any `scorer_name=` kwargs (`test_render_payload.py`), FIRST_SCORER grading cases (`test_settlement*.py`), and any FIRST_SCORER point totals in board tests.
- [ ] **Step 5 — Gate** → green.
- [ ] **Step 6 — Commit:** `git commit -am "refactor: remove FIRST_SCORER bet category from domain"`

---

### Task 3: Remove the orphaned goal timeline

After Task 2 nothing grades on goals; this removes the plumbing and the extra `/fixtures/events` API call.

**Files:**
- Modify: `tigrinho/providers/base.py`, `tigrinho/providers/api_football.py`, `tigrinho/providers/fake.py`, `tigrinho/domain/scoring.py`, `tigrinho/domain/settlement.py`, `tigrinho/cli.py`
- Test (modify): `tests/test_providers_base.py`, `tests/test_api_football_provider.py`, `tests/test_api_football_mapping.py`, `tests/test_fake_provider.py`, `tests/test_settlement.py`, `tests/test_settlement_apply.py`, `tests/test_poll_collect.py`, `tests/test_scoring.py`, `tests/test_cli_result.py`

- [ ] **Step 1 — `base.py`:** Delete the `GoalEvent` dataclass and remove the `goals: tuple[GoalEvent, ...]` field from `MatchResult`.
- [ ] **Step 2 — `api_football.py`:** Remove the `GoalEvent` import; delete `parse_goal_events`; remove the `goals=` parameter from `parse_match_result` (and its `goals=goals` arg); simplify `get_match_result` to `return parse_match_result(fixtures[0])` (drop the `/fixtures/events` call + `parse_goal_events`); delete the `_GOAL_DETAILS` constant and `Sequence` import if now unused.
- [ ] **Step 3 — `fake.py`:** Remove `goals=` from any scripted `MatchResult` construction.
- [ ] **Step 4 — `scoring.py`:** Remove the `GoalEvent`/`Stage`→`GoalEvent` import; delete `first_genuine_scorer`; remove the `goals` field from `MatchFacts`.
- [ ] **Step 5 — `settlement.py`:** Remove `goals=result.goals` from `match_facts_from_result`.
- [ ] **Step 6 — `cli.py`:** Remove the `GoalEvent` import and the `goals: tuple[GoalEvent, ...]` construction in the manual `result` command; call `MatchResult(...)` without `goals`.
- [ ] **Step 7 — Tests:** Remove `GoalEvent` tests (`test_providers_base.py`), the events-parsing / `get_match_result` events-call tests (`test_api_football_provider.py`, `test_api_football_mapping.py`), `goals=` from `MatchResult`/`MatchFacts` constructions in settlement/poll/scoring tests, the `first_genuine_scorer` test, and goal-entry assertions in `test_cli_result.py`.
- [ ] **Step 8 — Gate** → green.
- [ ] **Step 9 — Commit:** `git commit -am "refactor: remove now-unused goal timeline (drops /fixtures/events call)"`

---

### Task 4: Remove squad infrastructure

**Files:**
- Modify: `tigrinho/providers/base.py`, `tigrinho/providers/api_football.py`, `tigrinho/providers/fake.py`, `tigrinho/db/models.py`, `tigrinho/db/repositories.py`, `tigrinho/cli.py`
- Test (modify/delete): `tests/test_providers_base.py`, `tests/test_api_football_provider.py`, `tests/test_fake_provider.py`, `tests/test_repositories.py`, `tests/test_repositories_cache.py`, `tests/test_cli_sync.py`, `tests/test_cli.py`, `tests/test_cli_admin.py`, `tests/test_cli_crud.py`, `tests/test_cli_result.py`

- [ ] **Step 1 — `base.py`:** Delete the `SquadPlayer` value object and the `get_squad` method from the `FootballProvider` Protocol.
- [ ] **Step 2 — `api_football.py`:** Remove the `SquadPlayer` import; delete `parse_squad_players` and `get_squad`.
- [ ] **Step 3 — `fake.py`:** Remove the `SquadPlayer` import; delete the `squads` constructor field, `set_squad`, and `get_squad`.
- [ ] **Step 4 — `models.py`:** Delete the `SquadPlayer` ORM class and the `Game.first_scorer_player_id` column.
- [ ] **Step 5 — `repositories.py`:** Remove the `SquadPlayer` import and delete the entire `SquadRepository` class.
- [ ] **Step 6 — `cli.py`:** Remove the `SquadPlayer as SquadPlayerRow` and `SquadRepository` imports; delete the `squads_app` Typer group + `squads_seed` command (and its registration on the root app); remove the `first_scorer_player_id` line from `games show`; remove the `SquadPlayerRow` entry from the `db dump` models list.
- [ ] **Step 7 — Tests:** Delete `tests/test_cli_sync.py` (squad seed) and the squad cases in `test_repositories*.py`; remove `SquadPlayer`/`get_squad`/`set_squad` tests from provider tests; remove `first_scorer_player_id` assertions from CLI game-show tests; drop `squads`/`SquadPlayer` references in `test_cli*.py`.
- [ ] **Step 8 — Gate** → green. (ORM no longer declares `first_scorer_player_id`/`squad_players`; tests using `Base.metadata.create_all` simply don't create them. The migration test still uses the Alembic chain, fixed in Task 5.)
- [ ] **Step 9 — Commit:** `git commit -am "refactor: remove squad roster infrastructure (provider, model, repo, CLI)"`

---

### Task 5: Forward migration — drop column/table, purge FIRST_SCORER bets

**Files:**
- Create: `tigrinho/db/migrations/versions/<rev>_drop_first_scorer_and_squads.py`
- Test (modify): `tests/test_migrations.py`

- [ ] **Step 1 — Generate a revision id and create the migration.** Run `uv run alembic revision -m "drop first_scorer and squads"` to get a stamped file with a fresh `revision` id and `down_revision = "ed421d04f4c4"`, then replace its body with:

```python
"""drop first_scorer and squads

Removes the FIRST_SCORER bet category's storage: deletes existing FIRST_SCORER bets,
drops games.first_scorer_player_id, and drops the squad_players table.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "<rev>"  # keep the id Alembic generated
down_revision: str | Sequence[str] | None = "ed421d04f4c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema: purge FIRST_SCORER bets, drop the column and squad table."""
    op.execute("DELETE FROM bets WHERE category = 'FIRST_SCORER'")
    with op.batch_alter_table("games") as batch_op:
        batch_op.drop_column("first_scorer_player_id")
    op.drop_table("squad_players")


def downgrade() -> None:
    """Downgrade schema: recreate the column and squad table (no data restore)."""
    op.create_table(
        "squad_players",
        sa.Column("player_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("position", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("player_id"),
    )
    with op.batch_alter_table("games") as batch_op:
        batch_op.add_column(sa.Column("first_scorer_player_id", sa.Integer(), nullable=True))
```

- [ ] **Step 2 — Update `tests/test_migrations.py`:** Replace/extend the existing squad-table assertion. After `alembic upgrade head`, assert via `inspect(engine)` that `"squad_players" not in inspector.get_table_names()` and `"first_scorer_player_id" not in {c["name"] for c in inspector.get_columns("games")}`. Add a data test: stamp the base revision `ed421d04f4c4`, insert a `bets` row with `category='FIRST_SCORER'`, run `upgrade head`, assert that row is gone while a non-FIRST_SCORER bet survives.
- [ ] **Step 3 — Verify the migration runs:** `uv run alembic upgrade head` against a scratch DB succeeds; `uv run alembic downgrade -1 && uv run alembic upgrade head` round-trips.
- [ ] **Step 4 — Gate** → green.
- [ ] **Step 5 — Commit:** `git commit -am "feat(db): migration to drop first_scorer column + squad_players, purge FIRST_SCORER bets"`

---

### Task 6: Documentation sync

**Files:** `COMPLETION.md`, `README.md`, `PROGRESS.md`, `CLAUDE.md`

- [ ] **Step 1 — `COMPLETION.md`:** Update §6 (remove `first_scorer_player_id` + `squad_players`), §7.1 (remove `SquadPlayer`, `GoalEvent`, `get_squad`, `goals`), §7.2 (drop goal-timeline wording), §7.3 (one fewer call — `get_match_result` is a single fixtures call; no squad calls), §8.1 (remove FIRST_SCORER from the category/points table), §9 (remove first-scorer grading + own-goal/0x0 rules), §13 (remove squad seeding), and the module-map references.
- [ ] **Step 2 — `README.md`:** Remove first-scorer category + squad-seeding mentions.
- [ ] **Step 3 — `PROGRESS.md`:** Remove/annotate first-scorer & squad-sync items.
- [ ] **Step 4 — `CLAUDE.md`:** Module map — `repositories.py` (drop "squads"), `base.py` (drop "SquadPlayer").
- [ ] **Step 5 — Verify `/ajuda` ↔ COMPLETION.md parity** (CLAUDE.md non-negotiable #3): the `text_pt.help_text()` category list (4 categories, points from `POINTS`) matches the COMPLETION.md §8.1 table.
- [ ] **Step 6 — Gate** → green (docs don't affect tests, but run it).
- [ ] **Step 7 — Commit:** `git commit -am "docs: sync COMPLETION/README/PROGRESS/CLAUDE for FIRST_SCORER + squad removal"`

---

### Task 7: Final verification

- [ ] **Step 1 — Residue scan:** `grep -rniE "first.?scorer|FIRST_SCORER|squad|scorer|GoalEvent|first_genuine|\.goals\b" --include="*.py" tigrinho/ tests/` returns only intentional/unrelated hits (expect none for these terms).
- [ ] **Step 2 — Import smoke test:** `uv run python -c "import tigrinho.bootstrap, tigrinho.cli, tigrinho.bot.client"` succeeds.
- [ ] **Step 3 — Full gate** one final time → green.
- [ ] **Step 4 — Report** test count delta vs the 324 baseline.

## Self-Review

- **Spec coverage:** Every spec section maps to a task — domain→T2, providers→T3+T4, db model/repo→T4, migration→T5, bot→T1, cli→T3(goals)+T4(squads), tests→every task, docs→T6. ✓
- **Placeholders:** Migration code is shown in full; `<rev>` is the Alembic-generated id (explicitly noted to keep). No "TBD"/"handle edge cases". ✓
- **Type consistency:** `MatchResult`/`MatchFacts` lose `goals` together (T3); `render_payload` loses `scorer_name` in T2 after its only callers are removed in T1; `SettledGame.first_scorer_player_id` removed in T1 before the column is dropped in T4/T5. Ordering keeps each commit green. ✓
