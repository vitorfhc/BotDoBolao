# PROGRESS.md — TigrinhoDaCopa build state

Loop state for the Ralph build. The agent updates this **every iteration**: check off finished
items and append notes/blockers below. The authoritative spec is `COMPLETION.md`; the loop
operating rules are in `RALPH.md`.

## Milestones (do in order, one small step per iteration)
- [ ] **M0 — Scaffold:** `pyproject.toml`, ruff/mypy/pytest config, package layout, `config.py` (`.env` + `config.yaml` loading), `logging.py`. Gates green on an empty app.
  - [x] Project scaffold: `pyproject.toml` (uv project), ruff + mypy(strict) + pytest config, package layout (`tigrinho/` + `db`/`providers`/`domain`/`bot` subpackages), `.gitignore`, smoke test — all 4 gates green.
  - [ ] `config.py` (pydantic-settings: `.env` secrets + `config.yaml` via `YamlConfigSettingsSource`) — needs grounding.
  - [ ] `logging.py` (structlog setup).
- [ ] **M1 — Data layer:** ORM models, Alembic initial migration, repositories + tests.
- [ ] **M2 — Provider:** value objects + `FootballProvider` Protocol, `FakeProvider`, `ApiFootballProvider`, `RequestBudget` (hard-stop at cap) + tests.
- [ ] **M3 — Domain:** `bets.py`, `scoring.py`, `settlement.py` (pure) + exhaustive grading tests.
- [ ] **M4 — Bot skeleton:** discord.py client, startup config validation, `/ajuda`.
- [ ] **M5 — Sync cog:** daily fixtures sync, consolidated announcement + `@Tigrinhos` ping, reschedule/void handling.
- [ ] **M6 — Commands cog(s):** `/apostar` (components), `/minhas_apostas`, `/jogos`, bet CRUD, time-based closing; `/inscrever` & `/sair` (Tigrinhos role).
- [ ] **M7 — Poll cog:** active-window live polling, auto-settlement, results message, stuck-game alert.
- [ ] **M8 — Board cog:** `/placar geral|semana` with tie-breaks.
- [ ] **M9 — Admin CLI:** CRUD, manual result & re-settle, force sync & cache ops, recalc board & DB dump.
- [ ] **M10 — Deploy:** Dockerfile, compose, volume + config bind-mount, entrypoint migrations, `.env.example`, `config.example.yaml`, full README (§15.1), `CLAUDE.md`.
- [ ] **M11 — Hardening:** budget enforcement end-to-end, edge cases, coverage, `provider_mode: fake` smoke test.

## Notes / blockers / decisions
- **Iter 1 (M0 scaffold):** Chose `uv` as the project runner. Gates command is
  `uv run ruff check . && uv run ruff format --check . && uv run mypy --strict . && uv run pytest -q`.
  Pinned Python **3.12** via `.python-version` to match the prod image (`python:3.12-slim`);
  uv resolved CPython 3.12.8. Dev deps: ruff, mypy, pytest, pytest-asyncio (in `[dependency-groups].dev`).
  Runtime deps will be added per-milestone (after grounding each library) rather than all up-front.
  `config.yaml` is gitignored alongside `.env` (IDs treated as private per §4); `*.example` files
  committed at M10. mypy `exclude` set for `.venv`. `uv.lock` committed for reproducibility.
- **Next:** finish M0 — add `config.py`. Must web-search current `pydantic-settings` docs first
  (the `YamlConfigSettingsSource` + `settings_customise_sources` API) before coding it.
