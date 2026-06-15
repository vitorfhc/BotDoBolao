# PROGRESS.md — TigrinhoDaCopa build state

Loop state for the Ralph build. The agent updates this **every iteration**: check off finished
items and append notes/blockers below. The authoritative spec is `COMPLETION.md`; the loop
operating rules are in `RALPH.md`.

## Milestones (do in order, one small step per iteration)
- [ ] **M0 — Scaffold:** `pyproject.toml`, ruff/mypy/pytest config, package layout, `config.py` (`.env` + `config.yaml` loading), `logging.py`. Gates green on an empty app.
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
- (the loop appends entries here)
