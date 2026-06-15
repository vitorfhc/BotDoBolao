# PROGRESS.md — TigrinhoDaCopa build state

Loop state for the Ralph build. The agent updates this **every iteration**: check off finished
items and append notes/blockers below. The authoritative spec is `COMPLETION.md`; the loop
operating rules are in `RALPH.md`.

## Milestones (do in order, one small step per iteration)
- [ ] **M0 — Scaffold:** `pyproject.toml`, ruff/mypy/pytest config, package layout, `config.py` (`.env` + `config.yaml` loading), `logging.py`. Gates green on an empty app.
  - [x] Project scaffold: `pyproject.toml` (uv project), ruff + mypy(strict) + pytest config, package layout (`tigrinho/` + `db`/`providers`/`domain`/`bot` subpackages), `.gitignore`, smoke test — all 4 gates green.
  - [x] `config.py` — `Settings` (pydantic-settings 2.14.1): `.env` secrets + `config.yaml` via `YamlConfigSettingsSource`; env-over-yaml; `CONFIG_PATH`; fail-fast `ConfigError`; 12 tests.
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
- **Iter 2 (M0 `config.py`):** Grounded pydantic-settings 2.14.1 via web + introspection.
  `settings_customise_sources` returns sources highest-priority-first; ordering used is
  `init > env > .env > config.yaml(YamlConfigSettingsSource) > file_secrets` → env wins over YAML (§4).
  `YamlConfigSettingsSource(settings_cls, yaml_file=Path(CONFIG_PATH))` drives the YAML path from the
  `CONFIG_PATH` env var; missing YAML file resolves to empty (so required fields then fail-fast).
  Validation: IANA tz (`zoneinfo`), `HH:MM` sync_time, log level, `extra="forbid"` (unknown keys fail),
  positive-int IDs. Added deps: `pydantic-settings[yaml]`, `tzdata` (slim image lacks system zoneinfo).
  **mypy:** enabled `pydantic.mypy` plugin so a plain `Settings()` type-checks under `--strict`
  (the plugin special-cases `BaseSettings` source-population) — avoids an obscure `**{}` unpack and
  needs no `# type: ignore`.
- **Next:** finish M0 — add `logging.py` (structlog). Ground structlog config API first
  (processors, `configure`, JSON vs console renderer, stdlib integration).
