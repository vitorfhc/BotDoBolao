# Design: Full removal of the FIRST_SCORER bet + squad infrastructure

**Date:** 2026-06-15
**Status:** Approved (brainstorming) — ready for implementation plan
**Branch/worktree:** `worktree-cut-first-scorer`

## Goal

Remove the `FIRST_SCORER` bet category entirely, and everything that existed *only* to
support it: squad rosters (sync from API-Football + the cache table) and the per-goal
timeline. End state is a **4-category** bot — `EXACT_SCORE`, `BTTS`, `WINNER`,
`OVER_UNDER` — that needs only the 90' final scores + advancing team, and makes **no
`/fixtures/events` and no `/players/squads` API calls** at all.

## Decisions (locked during brainstorming)

1. **Cut depth: full.** Also remove the now-orphaned goal timeline (`GoalEvent`,
   `MatchResult.goals`, `MatchFacts.goals`, `first_genuine_scorer`, and the API-Football
   events parsing). After FIRST_SCORER is gone, nothing else consumes goals — the other
   four bets need only final scores + advancing team.
2. **DB change: new forward migration.** Add an Alembic migration (down_revision =
   `ed421d04f4c4`) that deletes existing `FIRST_SCORER` bets, drops
   `games.first_scorer_player_id`, and drops the `squad_players` table. `downgrade()`
   recreates the empty table/column (no data restore). Existing FIRST_SCORER bets and
   their leaderboard points are intentionally discarded; the scoreboard rebuilds from
   settled bets, so it self-corrects.

## Changes by layer

### Domain (`tigrinho/domain/`)
- **bets.py** — drop the `FIRST_SCORER` enum member, `FirstScorerPayload`, its arm of the
  `BetPayload` union, and the parse/serialize `match` arms.
- **scoring.py** — drop `FIRST_SCORER: 4` from `POINTS`; delete `first_genuine_scorer`;
  drop the `FirstScorerPayload` grading arm; remove `goals` from `MatchFacts`; drop the
  `GoalEvent` import.
- **settlement.py** — drop `goals=result.goals` from `match_facts_from_result`.
- **text_pt.py** — remove the `FirstScorerPayload` render arm + `scorer_name` parameter,
  the `Primeiro a marcar` label/example/order entries, and the two first-scorer rule
  bullets in `help_text()`.

### Providers (`tigrinho/providers/`)
- **base.py** — delete `GoalEvent`, `SquadPlayer`, `MatchResult.goals`, and the
  `get_squad` Protocol method.
- **api_football.py** — delete `parse_goal_events`, `parse_squad_players`, `get_squad`,
  and the `goals=` parameter on `parse_match_result`; simplify `get_match_result` to a
  single `/fixtures` call (no events fetch). Drop the `_GOAL_DETAILS` constant if now
  unused.
- **fake.py** — delete `squads`, `set_squad`, `get_squad`, and `goals` from any scripted
  results.

### DB (`tigrinho/db/`)
- **models.py** — delete the `SquadPlayer` ORM class and `Game.first_scorer_player_id`.
- **repositories.py** — delete `SquadRepository` and its `SquadPlayer` import.
- **New migration** (`down_revision = ed421d04f4c4`):
  `op.execute("DELETE FROM bets WHERE category = 'FIRST_SCORER'")`, then
  `with op.batch_alter_table("games") as batch_op: batch_op.drop_column("first_scorer_player_id")`,
  then `op.drop_table("squad_players")`. `downgrade()` recreates `squad_players` and the
  column (no data restore). SQLite + `render_as_batch=True` is already configured, so the
  column drop uses batch mode.

### Bot (`tigrinho/bot/`)
- **apostar_view.py** — remove `FIRST_SCORER` from `APOSTAR_CATEGORIES`; delete
  `ScorerChoice`, `load_scorer_choices`, `ScorerSelect`, `PageButton`,
  `build_squad_view`, and the FIRST_SCORER branch in `CategorySelect.callback`. Drop the
  `SquadRepository` import.
- **bets_cog.py** — drop the `SquadRepository`/`FirstScorerPayload` imports and the
  scorer-name resolver in `/minhas_apostas`.
- **poll_cog.py** — drop the `first_genuine_scorer` import, `SettledGame.first_scorer_player_id`,
  the `game.first_scorer_player_id = …` write, `resolve_scorer_name`, and the first-scorer
  line in `render_results_message`. Drop the `SquadRepository` import.
- **sync_cog.py** — drop `first_scorer_player_id=None` from new-game creation.

### CLI (`tigrinho/cli.py`)
- Remove the `squads` Typer subcommand group (`squads_seed`), the
  `SquadPlayer`/`SquadRepository` imports, the `first_scorer_player_id` line in
  `games show`, the `SquadPlayer` entry in `db dump`, and the `GoalEvent`/goals
  construction in the manual `result` command.

### Tests
- **Delete** first-scorer/squad-only files: `tests/test_apostar_scorer.py`; the squad
  tests in `tests/test_repositories*.py`; `tests/test_cli_sync.py` (or its squad portion);
  the `get_squad`/`set_squad`/`SquadPlayer` cases in provider tests.
- **Update** mixed files (scoring, bets, render_payload, settlement, poll_cog, bets_cog,
  board, apostar_flow/delete, migrations, providers_base, cli_*) to drop FIRST_SCORER /
  goals assertions. Per CLAUDE.md TDD: remove obsolete cases rather than weakening
  assertions; keep the rest meaningful.
- **Add** a migration test asserting the column/table are gone and FIRST_SCORER bets are
  purged.

### Docs
- **COMPLETION.md** — update §6 schema, §7.1/7.2 provider contract, §7.3 budget (one fewer
  call), §8.1 category + points table, §9 grading rules, §13 squad seeding, and the module
  map.
- **README.md / PROGRESS.md** — strip first-scorer/squad mentions.
- **CLAUDE.md** module map — `repositories.py` (no squads), `base.py` (no SquadPlayer).

## Verification

Full quality gate after each layer and at the end:

```
uv run ruff check . && uv run ruff format --check . && uv run mypy --strict . && uv run pytest -q
```

`mypy --strict` exhaustiveness checks on the `match` statements mechanically flag any
payload/category arm left unhandled — a strong safety net for this removal.
