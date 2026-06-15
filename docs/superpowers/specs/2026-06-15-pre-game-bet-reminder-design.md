# Design — Pre-Game Bet Reminder

**Date:** 2026-06-15
**Status:** Approved (design); pending spec review
**Spec authority:** Extends `COMPLETION.md` §9 (new §9.4) and §4 (config). If this design and the
live `discord.py` docs disagree, the live docs win (project rule #1). All `discord.py` surfaces used
here (`tasks.loop`, `commands.Cog`, `discord.AllowedMentions`) are already in use in `sync_cog.py` /
`poll_cog.py` — no new external surface is introduced.

## Goal

Post a **pre-game reminder** to the announce channel shortly before each match kicks off, **pinging
the `@Tigrinhos` role**, telling people the game is about to start and that they need to place their
bets before the opening whistle.

This fills a real gap between the two existing notifications:

- The **daily sync** announcement (`SyncCog`, once/day) pings `@Tigrinhos` when games *open* — but
  possibly long before kickoff.
- The **kickoff** message (`PollCog`, "🟢 Bola rolando!") posts *at* kickoff — when bets are already
  **closed**, with **no ping**.

The reminder is the in-between nudge: a heads-up **while betting is still open**.

## Decisions (from brainstorming)

- **Lead time:** ~**1 hour** before kickoff, exposed as config `reminder_lead_minutes` (default 60).
- **Recovery:** if the bot was offline at the ideal moment but is back up **while bets are still
  open** (`now < kickoff_utc`), it **fires late** — the reminder is still useful. If the game has
  already kicked off, it is skipped (bets closed).
- **Grouping:** when several games come due in the same tick (simultaneous WC kickoffs), send **one
  combined message** with a single `@Tigrinhos` ping (matches the §9.1 consolidated-announcement
  style; avoids spam).

## Constraints & key facts (verified)

- **Zero API-Football calls.** The reminder is driven entirely off `games.kickoff_utc`, already
  stored in the DB by the daily sync. It never touches the provider, so it costs **nothing** against
  `api_daily_cap` and works even when no provider is configured.
- The "special role" is the existing **`Tigrinhos` role** (`tigrinhos_role_id`) — per §12 it exists
  only to receive mentions in the announce channel. No new role concept.
- Betting closes purely by time (`now >= kickoff_utc`), independent of any API call (§6). The
  reminder's `now < kickoff_utc` bound therefore exactly coincides with "bets still open".

## Approach

A new dedicated **`ReminderCog`** with its own 1-minute `tasks.loop`, reading only the DB. It mirrors
the established "pure core function + thin cog" layout of `SyncCog`/`PollCog`. Because it needs no
provider, it registers in the DB-only block of `client.py` (alongside `BetsCog`/`BoardCog`).

**Rejected alternatives:**

- **Fold into `PollCog`** — would mix a budget-free, DB-only reminder into the provider/budget code
  path and couple reminder cadence to live polling. More entangled for no benefit.
- **Fold into `SyncCog`** — runs once daily; wrong cadence for an hourly-lead reminder.

## Components

### 1. Schema — one Alembic migration (`db/`)

Add one **nullable** column to `games` (model `db/models.py:Game`, plus migration):

- `reminder_sent_at: datetime | None` — set once when the pre-game reminder is posted for that game.

Defaults `NULL`. Persisting it makes the reminder **restart-safe and idempotent**: a restart never
re-pings a game already reminded. New migration `down_revision = "b7c3f1a9d2e4"` (current head).
Mirrors the existing `kickoff_announced_at` dedup column; the existing `announced_at` (daily
new-games announcement) and `kickoff_announced_at` (live kickoff) columns are **not** reused.

`_game_from_fixture` in `sync_cog.py` sets `reminder_sent_at=None` on insert (like the other dedup
columns).

### 2. Config (`config.py`, `config.example.yaml`, §4 table)

- New `Settings` field `reminder_lead_minutes: int = 60`, validated `> 0` (fail-fast at startup).
- Added to `config.example.yaml` with the default and a one-line comment, and to the COMPLETION.md
  §4 settings table.

### 3. Reschedule reset (`sync_cog.py:apply_plan`)

In the **rescheduled** branch (where `kickoff_utc`/`match_hash`/`status` are updated), also set
`game.reminder_sent_at = None`, so a moved game earns a **fresh** reminder for its new kickoff time.

### 4. Pure logic — no I/O, unit-tested (`reminder_cog.py`)

Kept Discord-free so it can be tested against a real SQLite session / plain value objects, matching
the module layout of `sync_cog.py` / `poll_cog.py` (pure core + thin cog):

- `select_due_reminders(open_games, *, now, lead_minutes) -> list[Game]` — pure filter. Keeps a game
  iff:
  - `reminder_sent_at is None` (not already reminded), **and**
  - `now >= kickoff_utc - timedelta(minutes=lead_minutes)` (inside the lead window), **and**
  - `now < kickoff_utc` (bets still open — this is what makes "fire late" fall out naturally; a
    game whose kickoff has passed is never reminded).

  Fed from `GameRepository.list_open(now)`, which already restricts to not-settled / not-voided games
  whose kickoff is in the future — so status filtering is handled by the query, and `select_due_*`
  only applies the lead-window + dedup logic. Ordered by `kickoff_utc` for stable message output.
- `format_reminder_announcement(games, *, role_mention, tz) -> str` — pt-BR combined message,
  singular/plural aware, one bullet per game with localized kickoff (same date/time formatting helper
  style as the §9.1 new-games announcement).

### 5. Cog + wiring (`reminder_cog.py`, `bot/client.py`)

`ReminderCog(commands.Cog)` with `tasks.loop(minutes=1)` and a `before_loop` that waits until ready,
mirroring the other cogs. It takes `settings`, `session_factory`, and an injectable `clock`
(determinism — no provider). Each tick (`run_reminders`):

1. Open a session; `due = select_due_reminders(GameRepository(session).list_open(now), now=now,
   lead_minutes=settings.reminder_lead_minutes)`.
2. If `due` is empty → return (no message, no commit needed).
3. Build the combined message via `format_reminder_announcement`; set `reminder_sent_at = now` on
   each due game; **commit**.
4. Send to `announce_channel_id` with `AllowedMentions(roles=True)`.

This is the same **commit-then-send / restart-safe** ordering the other cogs use: the dedup flag is
persisted before the network send, so a crash never double-pings (at the cost, shared with the other
cogs, of a rare lost message if the send itself fails after commit).

Registered in `client.py:_register_cogs` inside the `if self.session_factory is not None:` block —
**no `provider_factory` required**.

### 6. Edge cases

- **Bot offline through the window, back before kickoff** → fires late (window is
  `[kickoff - lead, kickoff)`).
- **Bot offline past kickoff** → never fires; `now >= kickoff_utc` excludes it and bets are closed.
- **Rescheduled game** → `reminder_sent_at` reset on reschedule → reminded again for the new time.
- **Postponed / cancelled (VOID)** → dropped by `list_open` (it filters `settled_at IS NULL`, and
  voiding sets `settled_at`) → never reminded.
- **Simultaneous kickoffs** → all due games in the tick are combined into one message / one ping.
- **Restart mid-window after already reminding** → persisted `reminder_sent_at` prevents a re-ping.
- **Lead longer than the game horizon** → harmless; a game simply qualifies as soon as it enters the
  window.

## Message copy (pt-BR, final wording in `text_pt.py` review)

Deliberately **no hardcoded minutes** (fire-late makes the actual lead vary), e.g.:

```
⏰ **Já vai começar!** As apostas fecham no apito inicial. <@&Tigrinhos>
• Brasil x Argentina — Sáb 16/06 16:00
Corra para apostar com /apostar! 🐯
```

Singular (one game) vs plural (multiple bullets) phrasing handled in `format_reminder_announcement`.
`<@&Tigrinhos>` shown for readability — the real string is `<@&{tigrinhos_role_id}>`.

## Testing (TDD)

- **Pure (`select_due_reminders`):** boundary just outside the window (no), at the lead edge (yes),
  inside (yes), at/after kickoff (no), already reminded (no), fire-late after downtime (yes); stable
  ordering by kickoff.
- **Pure (`format_reminder_announcement`):** single game vs multiple games, role mention present,
  localized kickoff in `timezone`.
- **DB/integration:** the cog path marks `reminder_sent_at` and produces exactly one message;
  re-running the same tick produces **no** second message (idempotent). `apply_plan` reschedule
  resets `reminder_sent_at`.
- **Config:** `reminder_lead_minutes` default and `> 0` validation.
- **Migration:** column added (upgrade) and removed (downgrade).
- All quality gates must pass: `ruff check`, `ruff format --check`, `mypy --strict`, `pytest -q`,
  under `provider_mode: fake` (offline, no secrets).

## Documentation (same change — project rule #3)

- `COMPLETION.md` — new **§9.4 "Pre-game reminder"** describing the time-based, no-API reminder, the
  `@Tigrinhos` ping, the lead window, and fire-late/combined behavior; add `reminder_lead_minutes` to
  the §4 settings table.
- `config.example.yaml` — add `reminder_lead_minutes` with its default and comment.
- `/ajuda` text in `domain/text_pt.py` — one line noting the `@Tigrinhos` role gets a heads-up ping
  shortly before kickoff so members know to bet in time (keeps §11/§12 accurate).

## Out of scope

- Per-user DM reminders or per-user opt-in beyond the existing role.
- Multiple staged reminders (e.g. both 1h and 10m) — single configurable lead only.
- Reminding about games with no real teams yet (placeholders are never inserted, §9.1).
- Any change to the daily-sync or kickoff/goal notifications.
