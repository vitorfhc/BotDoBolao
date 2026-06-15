# RALPH.md — TigrinhoDaCopa autonomous build loop

You are implementing the **TigrinhoDaCopa** Discord bot in this repository, fully autonomously,
**one small step per iteration**. You are run repeatedly with this same file; your previous work
persists in the files and in git history — build on it, don't restart it.

## Sources of truth
- **`COMPLETION.md`** — the authoritative spec (architecture, features, rules, config, and the
  milestone build order in §18). Re-read it every iteration. It overrides your assumptions.
- **`PROGRESS.md`** — the running checklist/state. Read it first; update it last. If it is
  missing, create it from the §18 milestones (M0–M11) as a checkbox list, commit, and stop.

## Each iteration — do exactly ONE focused, shippable unit of work
1. Read `COMPLETION.md` and `PROGRESS.md`. Choose the **single** next unchecked task, respecting
   milestone order (M0 → M11). Keep it small enough to finish, test, and commit in one iteration.
2. **Ground every external API first.** Before writing or changing any code that calls an external
   API or library surface (API-Football, `discord.py`, SQLAlchemy 2.0 / Alembic,
   `pydantic-settings`, Typer, `httpx`), **use web search** to read the current official docs and
   verify exact endpoints, fields, method signatures, intents, and permissions. If the live docs
   differ from `COMPLETION.md`, follow the docs and update `COMPLETION.md` in the same commit.
3. Implement with **TDD**: add a failing test, then minimal, strongly-typed code to pass it.
4. **Run all gates — they MUST pass before you finish the iteration:**
   `ruff check . && ruff format --check . && mypy --strict . && pytest -q`
   (use the project runner, e.g. `uv run …`, if one is configured). Never weaken, skip, `# type: ignore`,
   or delete tests just to go green.
5. Update `PROGRESS.md` (check off completed items; note discoveries, decisions, deferrals).
   Keep `/ajuda` text in sync if you changed commands, bet rules, or scoring (per §11).
6. Commit: `git add -A && git commit -m "<concise step description>"`.
7. **Stop.** Do not start another milestone in the same iteration.

## Guardrails
- Strong typing, fail-fast, pure domain logic, no real money.
- During development and tests use `provider_mode: fake` — **never call the real API** (protect the
  daily request budget). All tests must run offline with no secrets.
- Never delete or break working code. Prefer small, reversible commits.
- If blocked or uncertain, write the blocker into `PROGRESS.md`, make the smallest safe progress,
  commit, and stop.

## Completion — only when ALL of these are true
- Every milestone in `COMPLETION.md` §18 is implemented and checked off in `PROGRESS.md`.
- `ruff`, `mypy --strict`, and `pytest` all pass.
- `docker compose config` validates, and an end-to-end test using `provider_mode: fake` exercises
  sync → place bet → settle → scoreboard with **no network and no secrets**.
- `README.md` (full deployment guide, §15.1), `.env.example`, `config.example.yaml`, and
  `CLAUDE.md` all exist.

When and only when all of the above hold, output exactly this line:

`<promise>TIGRINHO COMPLETE</promise>`

Otherwise, keep working — pick the next task next iteration.
