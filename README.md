# TigrinhoDaCopa 🐯

A Discord bot for friendly **FIFA World Cup 2026** bets among friends — placar exato, primeiro a
marcar, ambos marcam, vencedor, e mais. Built and operated entirely in pt-BR for the players.

> **No real money.** This is a bragging-rights bolão — there are no payments, wagers, or payouts.

This README takes you from zero to a running bot. Every step is copy-paste runnable.

## 1. Overview

TigrinhoDaCopa announces newly-scheduled World Cup games in your Discord server, collects predictions
via slash commands, automatically grades them when each game ends, awards points, and keeps an
all-time and a weekly scoreboard.

Feature highlights:
- **4 bet categories** (exact score, both-teams-to-score, winner, over/under 2.5),
  graded on the **90-minute** result.
- **Component-driven `/apostar`** flow (selects + modal), editable until kickoff.
- **Automatic settlement** (self-healing — late finishers like extra time/penalties settle without
  manual steps) with a results message that mentions each player and their points.
- **Scoreboards**: `/placar geral` (whole tournament) and `/placar semana` (current week).
- **Notifications role** (`@Tigrinhos`) that anyone can opt in/out of — **not** required to bet.
- **No real money** — just diversão.

## 2. Prerequisites

- **Docker** and **Docker Compose** (`docker compose version`).
- A **Discord server** where you can create roles and manage their order (you need "Manage Server").
- An **API-Football** account (free tier works) for World Cup fixtures/results.

## 3. Create the Discord bot

1. Go to the **Discord Developer Portal** → <https://discord.com/developers/applications> → **New Application**.
2. Open **Bot** → **Add Bot** → **Reset Token** and copy the **token** (this is your `DISCORD_TOKEN`).
3. Required OAuth2 **scopes**: `bot`, `applications.commands`.
4. Required **bot permissions**: `Send Messages`, `Manage Roles`. (No privileged intents are needed.)
5. Under **OAuth2 → URL Generator**, tick those scopes + permissions, copy the generated **invite URL**,
   open it, and add the bot to your server.

## 4. Discord IDs & the role

1. In Discord, enable **Settings → Advanced → Developer Mode** (lets you right-click → "Copy ID").
2. Copy these IDs (right-click the server / channel / your user):
   - `guild_id` — your server.
   - `announce_channel_id` — the channel for announcements and results.
   - `admin_user_id` — your user (gets DM'd on errors/limits).
3. Create a role named **Tigrinhos**, right-click it → Copy ID → `tigrinhos_role_id`.
4. **Hierarchy:** in **Server Settings → Roles**, drag the **bot's role above** the `Tigrinhos` role.
   Discord forbids managing a role that sits at or above the bot's highest role.

## 5. Get the API-Football key

1. Sign up at <https://www.api-football.com/> (the dashboard shows your key) → this is `API_FOOTBALL_KEY`.
2. Note your plan's **daily request limit** (free tier ~100/day; paid plans much higher). The bot
   caps itself at `api_daily_cap` (default `3000`, comfortably under a 7,500/day plan) and hard-stops
   before exceeding it.
3. **Verify the World Cup 2026 league id and season** against the live API (the defaults are
   `wc_league_id: 1`, `wc_season: 2026`): query the `/leagues` endpoint and confirm the FIFA World Cup
   id, then set `wc_league_id` / `wc_season` in `config.yaml` accordingly.

## 6. Configure

```sh
cp .env.example .env                       # fill DISCORD_TOKEN and API_FOOTBALL_KEY
cp config.example.yaml config.yaml         # fill the four IDs; adjust settings as needed
```

Secrets live in `.env` (gitignored); everything else lives in `config.yaml`. See **COMPLETION.md §4**
for the full settings table (`provider_mode`, `timezone`, `sync_time`, `poll_interval_minutes`,
`match_window_hours`, `settle_grace_hours`, `stuck_recheck_minutes`, `api_daily_cap`, `db_path`,
`log_level`, `log_format`, …).

## 7. Run

```sh
docker compose up -d --build       # builds the image and starts the bot
docker compose logs -f             # watch startup; confirm slash commands registered
```

Database migrations (`alembic upgrade head`) run automatically on container start. The slash commands
are synced to your guild on startup (instant — no global propagation wait).

## 8. First-run setup

- **Force a sync** now (optional — otherwise it runs daily at `sync_time`):
  ```sh
  docker compose exec bot python -m tigrinho.cli sync run
  ```

## 9. Player guide (slash commands)

- `/apostar` — fazer ou editar um palpite (escolhe jogo → categoria → valor).
- `/minhas_apostas` — ver seus palpites (abertos e apurados) e apagar os abertos.
- `/jogos` — ver os jogos abertos e o que falta palpitar.
- `/placar [geral|semana]` — ver o ranking.
- `/inscrever` — receber os avisos de novos jogos (entra no cargo `@Tigrinhos`).
- `/sair` — parar de receber os avisos.
- `/ajuda` — ver a ajuda completa.

## 10. Admin CLI

Run any command inside the container: `docker compose exec bot python -m tigrinho.cli <group> <command>`.

- **CRUD**: `games list`, `games show <fixture_id>`, `players list`, `bets list [--game N|--player N]`,
  `bets delete <id> --confirm`.
- **Manual result & re-settle** (idempotent): `result set <fixture_id> <home> <away> [--advancing <team_id>]`.
- **Force sync**: `sync run`, `budget show` (API usage today + remaining).
- **Recalc & dump**: `board recalc [--periodo geral|semana]`, `db dump` (row counts per table).

Example:
```sh
docker compose exec bot python -m tigrinho.cli result set 215662 2 1
```

## 11. Operations

- **Database**: SQLite at `db_path` (default `/data/tigrinho.db`) on the named volume `tigrinho-data`.
  Back it up by copying the file out of the volume, e.g.:
  ```sh
  docker compose cp bot:/data/tigrinho.db ./backup-tigrinho.db
  ```
- **Logs**: `docker compose logs -f` (structured JSON to stdout).
- **Admin alerts**: the bot DMs `admin_user_id` on sync failures, a reached API cap, a game it can't
  auto-settle, or a role it can't manage.
- **API cap**: when the daily request cap is hit, the bot skips polling, logs it, and DMs the admin;
  bet closing is time-based and never consumes the budget.
- **Update / redeploy**: `git pull && docker compose up -d --build` (migrations re-run on start).

## 12. Troubleshooting

- **Bot can't assign the `@Tigrinhos` role** — give the bot `Manage Roles` and drag the bot's role
  **above** `Tigrinhos` in Server Settings → Roles (see §4).
- **Slash commands don't appear** — confirm the bot was invited with the `applications.commands` scope,
  that `guild_id` is correct, and check `docker compose logs` for the `commands_synced` line.
- **Games not showing** — almost always a wrong `wc_league_id` / `wc_season`; re-verify against the live
  API `/leagues` (see §5) and restart.
- **"API cap reached"** — you hit `api_daily_cap`; wait for the reset (`api_budget_reset_tz` midnight)
  or raise the cap if your plan allows. Check usage with `budget show`.
- **Wrong kickoff times** — set `timezone` (IANA, e.g. `America/Sao_Paulo`); it drives displayed
  kickoffs, the daily sync time, and the weekly reset.

## 13. Development

- Use **`provider_mode: fake`** for local/offline development — it never calls API-Football (so it
  needs no key and consumes no budget).
- Tooling (via [uv](https://docs.astral.sh/uv/)):
  ```sh
  uv sync                    # install deps
  uv run ruff check .        # lint
  uv run ruff format --check .
  uv run mypy --strict .     # types
  uv run pytest -q           # tests (offline, no secrets)
  ```

## 14. Disclaimer

TigrinhoDaCopa is for **friendly bets only — no real money**, no payments, no payouts. It is **not
affiliated with FIFA** or any official competition; team and fixture data come from API-Football.
