# TigrinhoDaCopa — Build Specification

A Discord bot for friendly (no real money) bets on **FIFA World Cup 2026** games.
This document is the single source of truth for an autonomous implementation loop. It is
written to be unambiguous: requirements use **MUST / SHOULD / MAY**, and every feature
states its inputs, outputs, and grading rules.

---

## 1. Product summary

A small friend group (the "Tigrinhos") predicts World Cup match outcomes in their Discord
server. The bot announces newly-scheduled games, collects predictions, automatically grades
them when each game ends, awards points, and keeps an all-time and a weekly scoreboard.
No money, no payments — just bragging rights.

**Anyone in the server can place bets.** The `Tigrinhos` role is opt-in and only controls who
gets @mentioned in announcements — it is **not** required to bet (see §12).

**Design priorities, in order:** correctness of grading → great usability (UX) → operability
(easy to debug/run) → simplicity.

---

## 2. Engineering principles (MUST follow)

- **Language/runtime:** Python **3.12+**.
- **Strong typing everywhere.** `mypy --strict` MUST pass with no `Any` leaks in domain code.
  Prefer `Enum`, `dataclass`/Pydantic models, and `typing.Protocol` over loose dicts.
- **Fail fast.** Validate all configuration at startup and crash with a clear message if
  anything required is missing or malformed. Never silently swallow exceptions in core flows.
- **Pure domain logic.** Bet grading, scoring, and settlement MUST be pure functions over
  value objects (no I/O, no clock, no DB). This makes them exhaustively unit-testable.
- **Deterministic & idempotent.** Re-running settlement for a game MUST reproduce identical
  results. The scoreboard MUST be fully rebuildable from stored bets + match results.
- **Small, focused modules.** Each unit has one clear purpose and a documented interface.
- **Quality gates (CI-style, run locally):** `ruff` (lint + format), `mypy --strict`,
  `pytest`. Domain logic (scoring/settlement) MUST have ~100% line+branch coverage.
- **Ground every external API in current docs (web search is MANDATORY).** Before writing or
  changing any code that touches an external API or third-party library surface — API-Football
  endpoints & response fields, `discord.py` interfaces/intents/permissions, SQLAlchemy 2.0 /
  Alembic, pydantic-settings' YAML source, Typer, etc. — the implementing agent MUST use **web
  search** to read the **current official documentation** and verify exact endpoints, parameters,
  response shapes, status codes, method signatures, and version compatibility. Never rely on
  memory or assumptions; field names and APIs drift. Record the doc URL in a comment/commit next
  to the integration. **If the live docs disagree with this spec, the live docs win** — follow
  them and update this document.

---

## 3. Technology choices (MUST use unless a blocker is found)

| Concern | Choice | Notes |
|---|---|---|
| Discord library | `discord.py` 2.x | Slash commands (app commands) + UI components (selects/buttons/modals). |
| Scheduling | `discord.ext.tasks` | Daily sync via `time=`; live polling via interval loop. No extra dep. |
| HTTP client | `httpx.AsyncClient` | Async network I/O (provider calls). |
| Database | SQLite via **SQLAlchemy 2.0** (typed ORM, **synchronous**) | Local SQLite queries are sub-ms; sync keeps the bot and CLI sharing identical repository code. Wrap in `asyncio.to_thread` only if contention ever appears. |
| Migrations | **Alembic** | Run `alembic upgrade head` on container start. |
| Admin CLI | **Typer** | Typed CLI; run via `docker compose exec`. |
| Config | **pydantic-settings** + YAML | Secrets from `.env`; all other settings from `config.yaml` (loaded via `YamlConfigSettingsSource`). Merged into one validated `Settings`; fail-fast. |
| Logging | **structlog** (or stdlib + JSON formatter) | Structured logs to stdout. |
| Tests | **pytest** + **pytest-asyncio** | Fake provider + temp SQLite. |
| Packaging | `pyproject.toml` | `uv` or `pip`. |

> Async split rationale: **network = async** (don't block the event loop), **local DB = sync**
> (trivially fast, simpler, shared with the CLI).

---

## 4. Configuration (secrets in `.env`, settings in `config.yaml`)

A single `Settings` object (pydantic-settings) is assembled from **two sources** and validated
at startup; the bot MUST refuse to start if any required value is missing or malformed.

- **Secrets** come from environment / **`.env`** (gitignored) — credentials only.
- **All other settings** come from **`config.yaml`** (non-secret), loaded via pydantic-settings'
  `YamlConfigSettingsSource`.
- The two sets are disjoint; if a key somehow appears in both, the environment wins.
- The location of the YAML file is taken from the **`CONFIG_PATH`** env var (default
  `./config.yaml`). This is the only non-secret value allowed in the environment (it must point
  to the settings file before the file can be read).

### 4.1 Secrets — `.env` (gitignored; commit `.env.example`)

| Variable | Required | Purpose |
|---|---|---|
| `DISCORD_TOKEN` | yes | Bot token. |
| `API_FOOTBALL_KEY` | yes | API-Football key. |

### 4.2 Settings — `config.yaml` (commit `config.example.yaml`)

| Key | Required | Default | Purpose |
|---|---|---|---|
| `guild_id` | yes | — | The single server the bot serves. |
| `announce_channel_id` | yes | — | Channel for new-game announcements and results. |
| `tigrinhos_role_id` | yes | — | Role pinged on announcements (notifications-only; see §12). |
| `admin_user_id` | yes | — | User DM'd on errors/limits. |
| `provider_mode` | no | `api_football` | `api_football` or `fake` (local/dev). |
| `api_football_base_url` | no | `https://v3.football.api-sports.io` | Provider base URL. |
| `wc_league_id` | no | `1` | FIFA World Cup league id (verify against provider). |
| `wc_season` | no | `2026` | Season. |
| `timezone` | no | `America/Sao_Paulo` | Drives sync time, displayed kickoffs, weekly reset. |
| `sync_time` | no | `06:00` | Daily fixtures sync (local time). |
| `reminder_lead_minutes` | no | `60` | Minutes before kickoff to ping `@Tigrinhos` with a "place your bets" reminder (§9.4). |
| `poll_interval_minutes` | no | `1` | Live-poll cadence during match windows (one request per cycle covers all games). |
| `match_window_hours` | no | `3` | Fast-poll window after kickoff; past it a game is "overdue" (rechecked slowly until the grace). |
| `settle_grace_hours` | no | `24` | Keep auto-settling a game until this long after kickoff (covers extra time/penalties + API lag); must be ≥ `match_window_hours`. |
| `stuck_recheck_minutes` | no | `15` | Recheck cadence for overdue games (past the match window, within the grace). |
| `api_daily_cap` | no | `3000` | Hard ceiling on provider requests per budget day (the paid plan allows 7500). |
| `api_budget_reset_tz` | no | `UTC` | Timezone whose midnight resets the request counter (API-Football resets at 00:00 UTC). |
| `db_path` | no | `/data/tigrinho.db` | SQLite file path (mounted volume). |
| `log_level` | no | `INFO` | Log level. |
| `log_format` | no | `json` | `json` or `console`. |

Example `config.yaml`:
```yaml
guild_id: 123456789012345678
announce_channel_id: 123456789012345678
tigrinhos_role_id: 123456789012345678
admin_user_id: 123456789012345678
provider_mode: api_football
api_football_base_url: https://v3.football.api-sports.io
wc_league_id: 1
wc_season: 2026
timezone: America/Sao_Paulo
sync_time: "06:00"
poll_interval_minutes: 1
match_window_hours: 3
settle_grace_hours: 24
stuck_recheck_minutes: 15
api_daily_cap: 3000
api_budget_reset_tz: UTC
db_path: /data/tigrinho.db
log_level: INFO
log_format: json
```

Both **`.env.example`** and **`config.example.yaml`** MUST be committed; the real `.env` (and,
if the IDs are considered private, `config.yaml`) MUST be gitignored.

---

## 5. Architecture & module layout

```
tigrinho/
  __init__.py
  config.py            # Settings: load .env (secrets) + config.yaml (settings), validate, fail-fast
  logging.py           # structlog setup
  db/
    engine.py          # SQLAlchemy engine/session factory
    models.py          # ORM models (typed)
    repositories.py    # CRUD repos: players, games, bets, api_usage
    migrations/        # Alembic
  providers/
    base.py            # FootballProvider Protocol + value objects (Fixture, MatchResult)
    api_football.py    # ApiFootballProvider (httpx) — maps API JSON -> value objects
    fake.py            # FakeProvider for tests/local (provider_mode: fake)
    budget.py          # RequestBudget — daily counter + hard stop at api_daily_cap
  domain/
    bets.py            # BetCategory enum, payload models, validation
    scoring.py         # points table + per-category grading (PURE)
    settlement.py      # grade all bets for a MatchResult (PURE)
    text_pt.py         # pt-BR message templates
  bot/
    client.py          # discord.py client + cog registration + config check on_ready
    sync_cog.py        # daily fixtures sync + announcements + reschedule/void handling
    poll_cog.py        # live polling + settlement + results messages
    bets_cog.py        # /apostar, /minhas_apostas, /jogos (bet CRUD + UI components)
    board_cog.py       # /placar
    subscribe_cog.py   # /inscrever, /sair (Tigrinhos role membership)
    help_cog.py        # /ajuda
    alerts.py          # admin DM alerts + structured logs
  cli.py               # Typer admin CLI
tests/
docker/                # Dockerfile, entrypoint
docker-compose.yml
.env.example
config.example.yaml
pyproject.toml
README.md
CLAUDE.md
```

---

## 6. Data model

SQLite tables (via SQLAlchemy models, created/evolved with Alembic).

**players**
- `discord_id` INTEGER PK
- `display_name` TEXT
- `created_at` TIMESTAMP (UTC)

A player row is **auto-created on the user's first bet**. Subscribing to notifications (§12)
does **not** create a player/scoreboard entry — the scoreboard only includes users who have
placed at least one bet.

**games**
- `fixture_id` INTEGER PK — **canonical id from the provider**
- `match_hash` TEXT — `sha256(f"{kickoff_iso}|{home_team_id}|{away_team_id}")`, a human-readable/dedup label only (NOT identity)
- `stage` TEXT — `GROUP` | `KNOCKOUT`
- `home_team_id` INTEGER, `home_team_name` TEXT
- `away_team_id` INTEGER, `away_team_name` TEXT
- `kickoff_utc` TIMESTAMP, `kickoff_local` TIMESTAMP (display) — note: all timestamps are stored
  tz-aware/UTC-normalized, so `kickoff_local` holds the **same instant** as `kickoff_utc`; display
  localization is done at render time from `kickoff_utc` via `timezone`.
- `status` TEXT — provider status normalized: `SCHEDULED|LIVE|FINISHED|POSTPONED|CANCELLED|VOID`
- `home_goals_90` INTEGER NULL, `away_goals_90` INTEGER NULL — **90′ result** (regulation incl. stoppage)
- `advancing_team_id` INTEGER NULL — for knockout winner grading
- `announced_at` TIMESTAMP NULL, `settled_at` TIMESTAMP NULL

**bets**
- `id` INTEGER PK
- `fixture_id` FK → games
- `player_discord_id` FK → players
- `category` TEXT — see §8.1
- `payload_json` TEXT — category-specific (validated against typed model)
- `created_at`, `updated_at` TIMESTAMP
- `is_correct` BOOLEAN NULL, `points_awarded` INTEGER NULL, `settled_at` TIMESTAMP NULL
- **UNIQUE(`fixture_id`, `player_discord_id`, `category`)** — enforces one bet per category per game

Bets are closed purely by time (`now >= kickoff_utc`), independent of any API call.

**api_usage** (request budget)
- `budget_date` DATE PK (in `api_budget_reset_tz`)
- `count` INTEGER

> Notification subscription state is **not** stored in the DB — the `Tigrinhos` Discord role is
> the single source of truth for who gets pinged.

---

## 7. Football data provider

### 7.1 Interface (provider-agnostic)

Define `FootballProvider` as a `Protocol` returning **value objects** (never raw JSON):

- `get_fixtures(window_hours: int) -> list[Fixture]` — upcoming WC fixtures within window.
- `get_recent_results(lookback_hours: int) -> list[MatchResult]` — **one** date-windowed call returning every WC fixture that kicked off within `lookback_hours`, with its current status **including finished ones** (the in-play-only `live=all` feed omits finished matches).
- `get_match_result(fixture_id: int) -> MatchResult` — final 90′ result for one game.

Value objects (frozen dataclasses): `Fixture`, `MatchResult` (carries `home_goals_90`,
`away_goals_90`, `advancing_team_id`, `status`, `stage`).

`ApiFootballProvider` implements this against API-Football v3. `FakeProvider` returns scripted
fixtures/results for tests and local development (selected via the `provider_mode` setting).

### 7.2 API-Football mapping (MUST be exact)

> ⚠️ **Ground this first.** The endpoint paths, field names, status codes, and the WC league id /
> season in §4 and §7 reflect prior knowledge and MUST be re-verified against the **current
> API-Football v3 documentation via web search** before implementing. If the live docs differ,
> follow them and update this section.

- **90′ score:** use `score.fulltime` (this is the regulation result; it **excludes** extra time).
  `score.extratime` / `score.penalty` are used **only** to derive `advancing_team_id`.
- **Live score:** the top-level `goals.{home,away}` is the current/live aggregate score; it
  populates `MatchResult.home_goals`/`away_goals`, used for goal notifications (§9.3). Distinct from
  `score.fulltime` (`home_goals_90`/`away_goals_90`, the regulation result used by settlement).
- **Stage:** `KNOCKOUT` if the fixture round is a knockout round (Round of 32/16, QF, SF, Final,
  3rd place); else `GROUP`.
- **Advancing team (knockout):** the side whose `teams.{home,away}.winner == true`.
- **Status normalization** (verified 2026-06 against live API-Football v3 docs; auth header
  `x-apisports-key`, base `https://v3.football.api-sports.io`): `NS/TBD → SCHEDULED`;
  `1H/HT/2H/ET/BT/P/SUSP/INT/LIVE → LIVE`; `FT/AET/PEN → FINISHED`; `PST → POSTPONED`;
  `CANC/ABD/AWD/WO → CANCELLED`. (`SUSP`/`INT` are transient in-play states; `AWD` technical-loss
  and `WO` walkover are "not played" outcomes → treated as cancelled, bets voided. An unknown short
  code is a fail-fast `ValueError`.)
- **Finished-game detection (settlement):** `?live=all` returns **only in-play** fixtures — finished
  matches drop out immediately — so the settlement path queries fixtures by **date window**
  (`/fixtures?league=&season=&from=&to=&timezone=UTC`), which returns each fixture's current
  `status.short` incl. `FT/AET/PEN`. One call covers all games. (Verified 2026-06 against the live docs.)
- **Transient errors:** retry timeouts/network errors and HTTP `429/500/502/503/504` with exponential
  backoff; only a successful request increments the budget counter.

### 7.3 Request budget (MUST — the hard limit the user requires)

A `RequestBudget` wraps every provider call:

1. Before each request, read today's count from `api_usage` (key = today in `api_budget_reset_tz`).
2. If `count >= api_daily_cap` (default **3000**), **do not make the request**. Raise/return a
   `BudgetExceeded` signal; the caller skips the work, logs it, and the bot DMs the admin **once
   per budget day**.
3. On a successful request, increment the count atomically.
4. Counter resets automatically when the budget date rolls over.

**Call-priority when the budget is tight (highest first):**
`daily fixtures sync` → `settlement reads at full-time` → `live polling`.
Live polling is the first thing to throttle/skip. Bet **closing never consumes budget** (time-based).

**Budget estimate (1-min polling):** one date-windowed status call per cycle covers **all** games
(in-play + finished), so detection is bounded at ~1,440/day even with several stuck games; plus ~1
read per finishing game (the authoritative final result) and 1 daily sync ≈ **~600–1,450 / 3,000**
on a busy World Cup day (the paid plan allows 7,500). No squad or goal-timeline calls are made.

---

## 8. Feature 1 — Bets

### 8.1 Bet categories, payloads, and grading (PURE functions)

All score-based grading uses the **90′ result** (`home_goals_90`, `away_goals_90`). `total90 =
home_goals_90 + away_goals_90`.

| Category | `BetCategory` | Payload | Wins when | Points |
|---|---|---|---|---|
| Exact score | `EXACT_SCORE` | `{home:int, away:int}` | both equal the 90′ score | **5** |
| Both teams to score | `BTTS` | `{sel: BOTH\|ONLY_HOME\|ONLY_AWAY\|NEITHER}` | the 90′ scoring pattern matches | **2** |
| Winner | `WINNER` | `{sel: HOME\|DRAW\|AWAY}` | see knockout rule below | **2** |
| Over/Under 2.5 | `OVER_UNDER` | `{sel: OVER\|UNDER}` | `OVER` ⇢ `total90 ≥ 3`; `UNDER` ⇢ `total90 ≤ 2` | **1** |

**Winner grading rule:**
- **Group stage:** compare to 90′ result — `HOME` if `home>away`, `DRAW` if equal, `AWAY` if `away>home`.
- **Knockout:** the official outcome is the **advancing team** (`HOME`/`AWAY`). A knockout is
  never a `DRAW`; a `DRAW` selection in a knockout always loses. **The bet UI MUST hide the
  `DRAW` option for knockout fixtures.**

**Points table is centralized** in `domain/scoring.py` (single constant) so it is trivial to tune.

### 8.2 Placing/editing bets (UX — MUST be component-driven)

Slash commands (pt-BR), all scoped to the configured `guild_id`. **No role is required to bet.**

- **`/apostar`** — opens an interactive flow:
  1. Select menu of **open** games (kickoff in the future, not started).
  2. Select menu of the 4 categories.
  3. A modal (or follow-up select) collects the category-specific input
     (e.g., score modal; team/option selects).
  4. Confirm → upsert the bet (respecting the one-per-category unique constraint). Editing an
     existing bet reuses the same flow and overwrites.
  - The flow MUST show current bets for the chosen game so editing is obvious.
- **`/minhas_apostas`** — lists the caller's bets grouped by game (open vs settled), with the
  payload rendered human-readably and, for settled games, ✓/✗ + points. Includes a **delete**
  control for still-open bets (the CRUD "delete").
- **`/jogos`** — lists upcoming/open games, kickoff (in `timezone`), stage, and whether the
  caller has bet in each category (quick "what's left to predict" view).

**Closing:** a bet is open only while `now < kickoff_utc`. Any attempt to create/edit/delete a
bet for a started game MUST be rejected with a clear pt-BR message. Closing requires **no** API call.

### 8.3 Settlement & results

When a game becomes `FINISHED` (see §9), the bot:
1. Builds a `MatchResult` (90′ score, advancing team).
2. Grades **every** bet on that game via `domain/settlement.py` (pure), writing
   `is_correct`/`points_awarded`/`settled_at`.
3. Posts **one** results message to `announce_channel_id`: the final 90′ score and **each
   participating player mentioned** with their total points from that game (and a per-category
   breakdown). Players with zero points are still acknowledged.
4. Marks the game `settled_at`. Settlement is **idempotent** (re-running corrects values).

---

## 9. Feature 2 — Games sync, polling & lifecycle

### 9.1 Daily fixtures sync (`sync_time`, default 06:00 `timezone`)

Flow (1 provider call, highest budget priority):
1. Fetch WC fixtures for the next **48h** (window configurable internally).
2. For each fixture **with both real teams decided** (skip placeholders like "Winner Group A"/TBD):
   - **New** (`fixture_id` unseen) → insert, queue for announcement.
   - **Rescheduled** (known `fixture_id`, kickoff changed) → update kickoff + `match_hash`, queue a
     re-announcement; existing bets remain valid (now tied to the new time).
   - **Postponed/Cancelled** (status) → set `status = VOID`, **void its bets** (no points),
     queue a player notification.
3. Send **one consolidated announcement** for all newly-opened games, **pinging
   `@Tigrinhos`** (the role). Re-announcements and void notices are separate concise messages.

Announcement text is pt-BR (example):
```
🐯 Novos jogos abertos para apostas! @Tigrinhos
• Brasil x Argentina — Sáb 16/06 16:00
• França x Alemanha — Sáb 16/06 19:00
Use /apostar para palpitar (fecha no apito inicial).
```

### 9.2 Live polling & auto-settlement

A `tasks.loop(minutes=poll_interval_minutes)` (default **1 min**) — **self-healing**:
1. Determine **pollable** games: kicked off and not yet settled, within `settle_grace_hours` of
   kickoff. If none, **return without any API call**.
2. **Cadence (`should_poll`, pure):** poll every cycle while any pollable game is within
   `match_window_hours` (live cadence). Once only **overdue** games remain (past the match window
   but within the grace), recheck only every `stuck_recheck_minutes` — a stuck game doesn't change
   minute-to-minute, so this avoids wasting budget.
3. When polling, make **one** date-windowed `get_recent_results(settle_grace_hours)` call (covers
   all games, in-play + finished); update each pollable game's `status`. For any now `FINISHED`,
   run settlement (§8.3), fetching `get_match_result()` once for the authoritative final result.
4. All calls go through `RequestBudget`. If the cap is hit, skip polling, log, DM admin once/day.

**Self-heal & stuck safeguard:** a game keeps being auto-settled until it finishes or outlives
`settle_grace_hours` (24h) — covering extra time/penalties and provider status lag with no manual
step. Only once a game is **still unsettled past the grace** does the bot DM the admin that it
**needs manual settlement** via the CLI (no more giving up at the 3h match window).

### 9.3 Live notifications (kickoff & goals)

The same per-cycle poll also posts live-match notifications to `announce_channel_id` (**no role
ping**):

1. **Kickoff** — when a game's status first becomes `LIVE`, the bot posts a "bola rolando" message
   (bets are now closed) exactly once (deduped via `games.kickoff_announced_at`).
2. **Goals** — the date-windowed `/fixtures` call also returns the **live score** (top-level
   `goals.{home,away}`), so a goal is detected for **free** by comparing it to the last-announced
   score (`games.last_announced_home_goals`/`last_announced_away_goals`). The message is the new
   **scoreline only** (no scorer — the goal timeline endpoint is not used). A disallowed goal (VAR,
   score drops) resyncs silently. Penalty-shootout kicks are **not** goals (the live `goals` field
   is match goals only).

Both are restart-safe and idempotent (dedup state persists on the game row).

---

## 10. Feature 3 — Scoreboard

- **`/placar [periodo: geral|semana]`** (default `geral`).
  - **Geral (full):** all-time points per player, descending. Lasts the whole tournament.
  - **Semana (weekly):** points from games whose **kickoff falls in the current Mon→Sun week in
    `timezone`**. Resets each Monday 00:00.
- Display: ranked list (top ~15) with medals for the top 3; if the caller is outside the top 15,
  append their own rank/points line.
- **Tie-break order:** (1) total points desc, (2) exact-score hits desc, (3) total correct bets
  desc, (4) earliest `players.created_at`.
- The board MUST be derivable purely from settled bets (so the CLI can rebuild it).

---

## 11. Feature 4 — Help (`/ajuda`)

`/ajuda` explains, in pt-BR: how the bolão works, every command (including `/inscrever` and
`/sair`), the bet categories with examples, the **points table**, the knockout 90′ rule, the
"bets close at kickoff" rule, and that the `Tigrinhos` role only affects mentions (not betting).

**Maintenance rule (MUST be enforced via `CLAUDE.md`):** any change to commands, bet categories,
scoring, or grading rules MUST update `/ajuda` text **and** this `COMPLETION.md` in the same change.

`CLAUDE.md` MUST also encode the **grounding rule** from §2 (web-search the official docs before
using or changing any external API) and the secrets-in-`.env` / settings-in-`config.yaml` split.

---

## 12. Feature 5 — Notification subscription (Tigrinhos role)

The **`Tigrinhos` role exists only to receive mentions/notifications** in the announce channel.
Membership is **self-service** and is **not** required to place bets — anyone in the server can
bet; the role only controls who gets pinged. Membership lives in Discord (the role itself); no DB
table is needed.

Commands (pt-BR, **ephemeral** replies so the channel stays clean):
- **`/inscrever`** — adds the caller to the `Tigrinhos` role (start receiving announcement pings).
  If already subscribed, reply with a friendly "você já está inscrito".
- **`/sair`** — removes the caller from the `Tigrinhos` role (stop receiving pings). If not
  subscribed, reply "você não está inscrito".

Requirements & failure handling:
- The bot MUST have the **Manage Roles** permission, and the `Tigrinhos` role MUST sit **below**
  the bot's highest role in the server hierarchy (otherwise Discord forbids the change).
- If the role can't be managed (missing permission / hierarchy), the command replies with a clear
  pt-BR error and the bot **DMs the admin**. This is also checked at startup (fail-fast warning).

---

## 13. Feature 6 — Admin CLI (Typer)

Run inside the container: `docker compose exec bot python -m tigrinho.cli <command>`.
The CLI shares the repository + domain code with the bot. Required capability groups:

1. **CRUD games/bets/players** — list/show/create/edit/delete any record.
2. **Manual result & re-settle** — set/override a game's 90′ score, then run (or re-run)
   settlement and scoring for that game. Idempotent.
3. **Force sync & budget** — trigger the fixtures sync on demand; print today's API request
   counter (and remaining budget).
4. **Recalc board & DB dump** — rebuild standings from scratch from settled bets; export/dump the
   SQLite DB (or specific tables) for debugging.

CLI output MUST be readable tables; destructive commands MUST require a confirmation flag.

---

## 14. Operability — logging & error alerts

- **Structured logs** (`structlog`) to stdout → visible via `docker compose logs`. Include
  fixture ids, counts, and budget usage on key events.
- **Admin DM alerts:** the bot DMs `admin_user_id` on important events —
  sync failure, **daily API cap reached** (once/day), a game that can't be auto-settled, a role
  it cannot manage, and any unhandled error in a scheduled task. Alerts are concise and actionable.
- Scheduled tasks MUST catch their own exceptions, log with context, alert, and keep the loop
  alive (one bad cycle never kills the bot).

---

## 15. Deployment (Docker + Compose)

- **Dockerfile:** `python:3.12-slim`, non-root user, dependencies from `pyproject.toml`.
  Entrypoint runs `alembic upgrade head` then launches the bot.
- **docker-compose.yml:** one `bot` service, `env_file: .env`, `restart: unless-stopped`, a
  named volume mounting `/data` so `db_path: /data/tigrinho.db` persists, and a bind-mount of
  `config.yaml` (read-only) with `CONFIG_PATH=/app/config.yaml`.
- **Discord setup:** invite the bot with `Manage Roles` + `Send Messages` + `applications.commands`;
  place the bot's role **above** `Tigrinhos` in the hierarchy. No privileged intents are required
  for these flows.
- **`.env.example`** and **`config.example.yaml`** committed with every secret/setting from §4.
- **`README.md` is a full deployment guide** for a brand-new operator — see the required outline
  in §15.1.

### 15.1 README — required contents (full deployment guide)

`README.md` MUST let someone with **no prior context** deploy the bot from zero, with every step
copy-paste runnable. Default language English (pt-BR acceptable if the team prefers). Required
sections, in order:

1. **Overview** — what TigrinhoDaCopa does (pt-BR World Cup 2026 friendly bets), feature
   highlights, and a clear "no real money" note.
2. **Prerequisites** — Docker + Docker Compose; a Discord server where you can manage roles; an
   API-Football account.
3. **Create the Discord bot** — register an application + bot in the Discord Developer Portal and
   copy the **token**; required scopes (`bot`, `applications.commands`) and permissions
   (`Send Messages`, `Manage Roles`); how to build the OAuth2 invite URL and add the bot.
4. **Discord IDs & the role** — enable Developer Mode; copy `guild_id`, `announce_channel_id`, and
   your `admin_user_id`; create the `Tigrinhos` role, copy `tigrinhos_role_id`, and **place the
   bot's role above it** in the hierarchy.
5. **Get the API-Football key** — sign up, copy the key, note the free-tier daily limit, and how to
   **verify the WC-2026 league id & season** against the current API/docs.
6. **Configure** — `cp .env.example .env` (fill the two secrets) and `cp config.example.yaml
   config.yaml` (fill IDs, adjust settings); include a reference table of every setting (or link to §4).
7. **Run** — `docker compose up -d --build`; migrations run automatically on start;
   `docker compose logs -f` to watch startup and confirm slash commands registered.
8. **First-run setup** — optionally force a sync via the CLI to populate games.
9. **Player guide** — every slash command (`/apostar`, `/minhas_apostas`, `/jogos`, `/placar`,
   `/inscrever`, `/sair`, `/ajuda`) with one-line descriptions.
10. **Admin CLI** — how to exec into the container and run each capability group, with examples.
11. **Operations** — where the SQLite DB lives (the `/data` volume) and how to back it up; reading
    logs; admin DM alerts; behavior when the daily API cap is hit; updating/redeploying.
12. **Troubleshooting** — common failures and fixes: bot can't assign the role (permission /
    hierarchy), slash commands not appearing (guild sync), games not showing (wrong league id /
    season — re-verify via docs), API cap reached, timezone surprises.
13. **Development** — run locally with `provider_mode: fake`; run `pytest`, `ruff`, `mypy`.
14. **Disclaimer** — friendly bets only, no real money, not affiliated with FIFA.

---

## 16. Testing strategy

- **Domain (highest priority, ~100% coverage):** table-driven unit tests for every bet category,
  including edge cases — knockout 90′ draw, advancing-team winner, over/under boundary at exactly
  2 and 3 goals, BTTS NEITHER on 0-0.
- **Settlement:** idempotency (running twice yields identical points) and full-game grading.
- **Repositories:** CRUD against a temp SQLite; the one-bet-per-category constraint.
- **Provider:** `ApiFootballProvider` JSON→value-object mapping with recorded fixtures (use the
  `score.fulltime` vs ET/penalty distinction as explicit cases). `RequestBudget` hard-stop at cap.
- **Config:** loading merges `.env` + `config.yaml`; missing required values fail fast.
- **Bot flows:** thin; rely on `FakeProvider`. Cover sync (new/reschedule/void), the active-window
  polling decision (no API call when no active games), and subscribe/unsubscribe role toggling.

---

## 17. Rules summary (quick reference)

- Anyone in the server can bet; the `Tigrinhos` role is notifications-only, self-service via
  `/inscrever` / `/sair`, and **not** required to bet.
- One bet per category per game; all categories optional; editable until kickoff; closing is
  time-based (no API call).
- Score-based bets (exact score, BTTS, over/under) grade on the **90′** result.
- Winner: group = 90′ 1X2 (draw allowed); knockout = advancing team (no draw; UI hides draw).
- Over/Under 2.5: Over = total90 ≥ 3, Under = total90 ≤ 2.
- Canonical game id = provider `fixture_id`; reschedule updates in place; cancel ⇒ VOID + bets voided + notify.
- Hard stop at `api_daily_cap` (default 3000) requests/day; priority sync > settlement > polling.
- Weekly board = current Mon→Sun in `America/Sao_Paulo`; full board = whole tournament.
- Secrets live in `.env`; every other setting lives in `config.yaml`.
- Ground every external API/library in current docs via web search **before** coding it (live docs win).

---

## 18. Build order (milestones for the loop)

Each milestone is independently testable; do them in order. Before any milestone that integrates
an external API or library, **ground it first** — web-search the current official docs (per §2)
and code against them.

- **M0 — Scaffold:** `pyproject.toml`, ruff/mypy/pytest config, package layout, `config.py`
  (`.env` + `config.yaml` loading), `logging.py`. Gates green on an empty app.
- **M1 — Data layer:** models, Alembic initial migration, repositories + tests.
- **M2 — Provider:** `base.py` value objects + Protocol, `FakeProvider`, `ApiFootballProvider`,
  `RequestBudget` + tests (mock httpx; budget hard-stop).
- **M3 — Domain:** `bets.py`, `scoring.py`, `settlement.py` (pure) + exhaustive tests (§16).
- **M4 — Bot skeleton:** client, startup config validation, `/ajuda`.
- **M5 — Sync cog:** daily fixtures sync, consolidated announcement w/ role ping, reschedule/void.
- **M6 — Commands cog(s):** `/apostar` (components), `/minhas_apostas`, `/jogos`, bet CRUD,
  time-based closing; `/inscrever` & `/sair` (Tigrinhos role membership).
- **M7 — Poll cog:** active-window live polling, auto-settlement, results message, stuck-game alert.
- **M8 — Board cog:** `/placar geral|semana` with tie-breaks.
- **M9 — Admin CLI:** all four capability groups.
- **M10 — Deploy:** Dockerfile, compose, volume + config bind-mount, entrypoint migrations,
  `.env.example`, `config.example.yaml`, **full README (§15.1)**, CLAUDE.md.
- **M11 — Hardening:** budget enforcement end-to-end, edge cases, coverage, manual smoke test with `FakeProvider`.

---

## 19. Assumptions & defaults (override here if wrong)

- Single Discord server (one guild). No multi-tenant support.
- Admin actions are CLI-only (the bot exposes no admin slash commands; only DM alerts).
  `/inscrever` and `/sair` are ordinary user commands, not admin.
- Notification opt-in = membership in the `Tigrinhos` role, managed by `/inscrever` / `/sair`;
  it is independent of betting.
- `wc_league_id=1`, `wc_season=2026` for API-Football — **verify** against the live API before release.
