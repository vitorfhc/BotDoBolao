# CLAUDE.md — TigrinhoDaCopa

A Discord bot for friendly (no real money) bets on **FIFA World Cup 2026** games. The authoritative
spec is **`COMPLETION.md`**; this file is the working contract for anyone (human or AI) changing the code.

## Non-negotiable rules

1. **Ground every external API in current docs (web search MANDATORY).** Before writing or changing any
   code that touches an external API or third-party library surface — API-Football v3 endpoints/fields,
   `discord.py` intents/permissions/UI, SQLAlchemy 2.0 / Alembic, `pydantic-settings`, `Typer`, `httpx` —
   **web-search the current official documentation** and verify exact endpoints, fields, signatures, and
   versions. Never rely on memory. **If the live docs disagree with `COMPLETION.md`, the live docs win** —
   follow them and update `COMPLETION.md` in the same change. Record the doc URL in a comment.

2. **Secrets in `.env`, settings in `config.yaml`.** Credentials (`DISCORD_TOKEN`, `API_FOOTBALL_KEY`)
   come only from the environment / `.env` (gitignored). Every other setting comes from `config.yaml`
   (loaded via pydantic-settings' `YamlConfigSettingsSource`; path from `CONFIG_PATH`). The two sets are
   disjoint; if a key appears in both, the environment wins. See `tigrinho/config.py` and COMPLETION.md §4.
   Commit only `.env.example` / `config.example.yaml`.

3. **Keep `/ajuda` and `COMPLETION.md` in sync.** Any change to commands, bet categories, scoring, or
   grading rules MUST update the pt-BR `/ajuda` text in `tigrinho/domain/text_pt.py` **and**
   `COMPLETION.md` in the same change. (The points table in `/ajuda` is derived from
   `domain/scoring.POINTS`, so it stays in sync automatically — keep it that way.)

## Engineering principles

- Python **3.12+**, **strong typing** (`mypy --strict`, no `Any` leaks in domain code).
- **Fail fast**: validate config at startup; never silently swallow exceptions in core flows.
- **Pure domain**: bet grading/scoring/settlement (`tigrinho/domain/`) are pure functions over value
  objects — no I/O, no clock, no DB — and are exhaustively unit-tested (~100% on scoring/settlement).
- **TDD**: write a failing test first, then minimal typed code to pass it. Never weaken/skip/`# type: ignore`
  or delete tests to go green.
- **Determinism**: inject `now`/clocks; settlement is idempotent; the scoreboard rebuilds from settled bets.

## Quality gates (must all pass)

```
uv run ruff check . && uv run ruff format --check . && uv run mypy --strict . && uv run pytest -q
```

## Dev / run

- **Local dev & all tests use `provider_mode: fake`** — never call the real API-Football (protects the
  daily request budget). Tests run offline with no secrets.
- Run the bot: `python -m tigrinho`. Admin CLI: `python -m tigrinho.cli <group> <command>`
  (e.g. `docker compose exec bot python -m tigrinho.cli budget show`).
- Migrations: `alembic upgrade head` (the container entrypoint runs this before the bot).

## Module map (`tigrinho/`)

- `config.py` — `Settings` (`.env` + `config.yaml`), fail-fast. `logging.py` — structlog setup.
- `db/` — `models.py` (typed ORM + `TZDateTime`), `engine.py`, `repositories.py`, `migrations/` (Alembic).
- `providers/` — `base.py` (value objects + `FootballProvider` Protocol), `fake.py`, `api_football.py`,
  `budget.py` (`RequestBudget` hard-stop).
- `domain/` — `bets.py` (categories/payloads), `scoring.py` (points + grading), `settlement.py`, `text_pt.py`.
- `bot/` — `client.py` (`TigrinhoBot`), `*_cog.py` (sync, poll, bets, board, subscribe, help), `alerts.py`.
- `bootstrap.py` — composition root (`build_provider`, `create_bot`, `run`). `cli.py` — admin Typer CLI.
