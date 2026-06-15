# Reliable & snappier settlement polling

**Date:** 2026-06-15
**Branch:** `feat/reliable-polling`
**Status:** approved (brainstorm) → implementing

## Context & goal

The API-Football plan was upgraded from the free tier (100 requests/day) to **7,500
requests/day**. The bot's settlement flow was tuned for the tiny free budget: it polls every
10 minutes and gives up on a game 3 hours after kickoff (DMing the admin to settle by CLI).

Goal: make settlement **snappier** (results posted within ~1 minute of full-time) and **more
reliable** (no manual intervention in practice), spending the now-ample budget. This is *not* a
new live-event feed — same final-result behavior, just faster and self-healing.

## Key finding (live docs win — CLAUDE.md rule #1)

Verified against `https://www.api-football.com/documentation-v3` (2026-06):

- **`GET /fixtures?live=all` returns only *in-play* fixtures.** Finished matches (`FT`/`AET`/`PEN`)
  drop out of the live feed immediately.
- **`GET /fixtures?league=&season=&from=&to=` (dates `YYYY-MM-DD`) returns *all* fixtures in the
  range with their current `status.short`,** including finished ones. (Same call `get_fixtures`
  already uses.)
- Status can lag for competitions without livescore (docs: "up to 48 hours"). The World Cup has
  livescore, but this justifies a generous self-heal grace.

**Consequence:** the current detection — waiting to *catch* a game showing `FINISHED` in the
`live=all` feed — is a latent bug. In production a finished game never appears as `FINISHED` in
that feed, so `collect_settlements` would never settle. (Tests pass only because `FakeProvider`
returns `FINISHED` from its live results, unlike the real API.)

## Design

### 1. Reliable detection — date-windowed results
Replace the `live=all` call in the settlement path with a **date-windowed `/fixtures` fetch**
that returns each game's current status (incl. `FT`/`AET`/`PEN`). One request covers every game
in the window, in-play and finished alike. Provider gets `get_recent_results(lookback_hours)`;
`get_live_results` is removed (its only caller was the settlement path).

Goal events for the first-scorer rule are still fetched per finishing game via the existing
`get_match_result(fixture_id)` (one-time, when a game is first seen finished).

### 2. Snappier + cadence-gated polling
- `poll_interval_minutes`: **10 → 1** (loop fires every minute).
- A game within `match_window_hours` (3h) of kickoff is "active" → polled every cycle (fast).
- A game past 3h but within the grace is "overdue" → re-checked only every
  `stuck_recheck_minutes` (**15**), not every minute (a stuck game doesn't change minute-to-minute).
- The "should we call the provider this cycle?" decision is a **pure function** (`should_poll`),
  unit-tested; the cog only does I/O.

### 3. Self-heal stuck recovery
- Keep auto-settling any kicked-off, unsettled game until `settle_grace_hours` (**24h**) past
  kickoff. Covers extra-time/penalties and API status lag with zero manual work.
- DM the admin **only** once a game is still unsettled *after* the grace (true last resort), not
  at the old 3h cliff.

### 4. Retry with backoff
Wrap each provider HTTP call in a small retry (`retry_async`, a pure helper with an injected
sleep): retry transient failures only — `httpx.TimeoutException`, transport errors, and HTTP
`429/500/502/503/504` — up to 2 retries with exponential backoff. Non-transient errors and
`BudgetExceeded` are not retried. The budget is re-checked before each attempt; only a successful
attempt increments the counter.

### 5. Budget hard-stop & cap
- `api_daily_cap`: **100 → 3,000**. The cap is a *safety* ceiling enforced at the HTTP boundary
  (`RequestBudget.run` raises `BudgetExceeded` before the request) — overage is structurally
  impossible; at worst polling degrades for the rest of the budget day.

## Budget math (poll every 1 min)

| Item | Requests/day |
|---|---|
| Date-windowed status poll (1 req/cycle, covers ALL games incl. stuck) | ≤ 1,440 (24/7 ceiling); ~600 typical |
| Settlement events (`get_match_result`, 2 req × ~6 games) | ~12 |
| Daily fixtures sync | 1 |
| **Total (even with several stuck games)** | **~600–1,450** |

Because one batch call covers every game, stuck-game count does **not** multiply cost (the earlier
worry about per-game polling is moot). Realistic usage ≈ 8–19% of 7,500; cap 3,000 leaves 2.5×
headroom and trips long before the real limit if something runs away.

## New/changed settings

| Setting | Old | New | Meaning |
|---|---|---|---|
| `poll_interval_minutes` | 10 | **1** | loop cadence |
| `api_daily_cap` | 100 | **3000** | safety hard-stop |
| `match_window_hours` | 3 | 3 (unchanged) | fast-poll window after kickoff |
| `settle_grace_hours` | — | **24** | keep auto-settling until this long after kickoff |
| `stuck_recheck_minutes` | — | **15** | recheck cadence for overdue (post-window) games |

## Testing
- `should_poll` and `retry_async`: pure unit tests (no I/O, injected clock/sleep).
- Provider: `get_recent_results` mapping + retry behavior via `httpx.MockTransport` + recorded JSON.
- Repository: pollable / overdue queries against a temp SQLite.
- Poll cog: self-heal end-to-end (game finishes late, auto-settles; admin DM only past grace) via
  `FakeProvider` + real session.
- Update the e2e and budget-e2e tests for the new detection method.

## Out of scope
Live event feed (goal/HT/FT announcements), live odds/win-probability, more frequent re-sync.
Documented as future options; not built here.
