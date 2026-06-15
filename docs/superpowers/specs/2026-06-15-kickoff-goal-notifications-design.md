# Design — Kickoff & Goal Notifications

**Date:** 2026-06-15
**Status:** Approved (design); pending spec review
**Spec authority:** Extends `COMPLETION.md` §8.3 / §9.2. If this design and the live API-Football v3
docs disagree, the live docs win (project rule #1).

## Goal

Make the bot post two new live-match notifications to the announce channel:

1. **Kickoff** — when a match actually starts (bets are now closed).
2. **Every goal** — with the scorer's name and minute when available.

Both post to `announce_channel_id` (the same channel as results and the daily new-games
announcement). **Neither pings the Tigrinhos role** (decision: avoid spam during a busy match). The
existing finished-game results message is unchanged.

## Constraints & key facts (verified)

- The bot is **poll-based** (`PollCog`, `tasks.loop`), default `poll_interval_minutes: 1`. While a
  game is within `match_window_hours` (3h) of kickoff, `should_poll` returns `True` every cycle, so
  live games are already polled once per minute. **No cadence change is needed**; notification
  latency is ≤1 min.
- The per-cycle settlement path makes **one date-windowed `/fixtures` call**
  (`get_recent_results(settle_grace_hours)`) that returns every in-window fixture's current status.
- **Verified against live API-Football v3 docs (2026-06):** the `/fixtures` response carries a
  top-level `goals: {home, away}` object holding the **current/live** score (refreshed ~every 15s),
  separate from `score.{halftime,fulltime,extratime,penalty}`. Recommended call rate is 1/min while
  a fixture is in play — matches our existing cadence.
  Source: https://www.api-football.com/documentation-v3
- **Budget:** goal detection reads the live score from the call we already make → **zero extra API
  requests**. Scorer detail (`/fixtures/events` via `get_match_result`) is fetched **only when a
  score changes** (~1–2 requests per goal). Worst-case a 7-goal game ≈ 14 requests, negligible vs
  `api_daily_cap: 3000`.

## Approach

Extend the existing 1-minute poll cycle to emit lifecycle events; do not add a second loop.

**Rejected alternatives:** a separate high-frequency live loop, or polling `/fixtures/events`
per live game every cycle. Both add API spend and a second moving part for no benefit, because the
live score is already free in the per-cycle call.

## Components

### 1. Provider — surface the live score (`providers/`)

- `MatchResult` (`providers/base.py`) gains two fields: `home_goals: int | None`,
  `away_goals: int | None` — the **current/live aggregate** score (API top-level `goals` field).
  Documented as distinct from `home_goals_90`/`away_goals_90` (regulation 90', `score.fulltime`,
  used only by settlement).
- `parse_match_result` (`providers/api_football.py`) reads `item["goals"]` into the new fields
  (`_opt_int`, tolerant of `null`). No new endpoint call — same `/fixtures` item.
- `get_recent_results` now carries the live score automatically (same items).
- `FakeProvider` (`providers/fake.py`) updated to populate the live score and to support a scripted
  timeline (kickoff → goal → goal → finish) so the flow is exercisable offline.

### 2. Schema — one Alembic migration (`db/`)

Add three **nullable** columns to `games` (model `db/models.py:Game`, plus migration):

- `kickoff_announced_at: datetime | None` — set once when the kickoff message is posted.
- `last_announced_home_goals: int | None` — live score we've announced up to (home).
- `last_announced_away_goals: int | None` — live score we've announced up to (away).

All three default `NULL`. Persisting them makes detection **restart-safe and idempotent**: a
restart never re-announces a kickoff or goal already posted. (The existing `announced_at` column is
the daily new-games announcement and is **not** reused.)

### 3. Pure logic — no I/O, unit-tested (~100%)

In `poll_cog.py`, alongside the existing pure helpers (`render_results_message`,
`apply_settlement`), to match the current module layout (rendering/detection stays pure; the cog
does the I/O):

- `detect_kickoff(status, kickoff_announced_at) -> bool` — `True` iff `status is LIVE` and
  `kickoff_announced_at is None`.
- `detect_goal_deltas(stored_home, stored_away, current_home, current_away) -> GoalDelta` —
  returns new-goal counts per side. **Decreases are ignored** (VAR/disallowed): they produce no
  message and simply resync `last_announced_*` downward. Treats `None` stored as 0.
- `render_kickoff_message(home_name, away_name) -> str` — pt-BR.
- `render_goal_message(...) -> str` — pt-BR; takes scoreline + best-effort scorer (name, minute,
  is_own_goal, is_penalty).

### 4. Poll-cycle wiring (`poll_cog.py`)

Extend the per-game loop in `collect_settlements` (and the message-posting in `run_poll` /
`_post_results`) so each pollable game, from the single date-windowed call, is handled as:

1. **Kickoff:** `detect_kickoff(...)` → queue kickoff message; set `kickoff_announced_at = now`.
2. **Goal:** compare live score to `last_announced_*` via `detect_goal_deltas(...)`. If any side
   rose: fetch `get_match_result(fixture_id)` **once**, match the new scorer(s) from the goal
   timeline (latest unannounced events for the side that increased), queue a goal message per new
   goal; set `last_announced_* = current`. If the side dropped, just resync `last_announced_*` (no
   message).
3. **Finished:** settle exactly as today (`apply_settlement`, results message).

The new messages post to `announce_channel_id`, **no role ping** (`AllowedMentions` with the role
suppressed). Ordering within a cycle: kickoff, then goals (minute order), then result.

### 5. Edge cases

- **VAR / disallowed goal** — live score drops → silent resync, no message.
- **Events feed lags the score field** — if `get_match_result` returns fewer goals than the live
  score implies, announce with "👟 artilheiro a confirmar" and still show the correct scoreline;
  `last_announced_*` advances so we never double-announce.
- **Own goal / penalty** — annotated from event flags ("gol contra" / "de pênalti").
- **Penalty shootout (knockout)** — excluded: the live `goals` field is match goals only; shootout
  kicks live in `score.penalty` and are never counted as goals.
- **Restart mid-match** — persisted columns mean no re-announcement; first poll after restart
  resyncs silently if nothing changed.
- **Stoppage time** — goal minute uses the event's `elapsed` value (existing `GoalEvent.minute`).

## Message copy (pt-BR, final wording in `text_pt.py` review)

- Kickoff: `🟢 **Bola rolando!** {home} x {away} — as apostas estão encerradas. 🐯`
- Goal: `⚽ **GOOOL do {team}!** {home} {h}x{a} {away} — 👟 {scorer} ({minute}')`
  - own goal: `… — 👟 {scorer} ({minute}', gol contra)`
  - penalty: `… — 👟 {scorer} ({minute}', de pênalti)`
  - unknown scorer: `… — 👟 artilheiro a confirmar`

## Testing

- **Pure:** `detect_kickoff`, `detect_goal_deltas` (including decrease/None/multi-goal cycles), and
  both renderers (own goal, penalty, unknown scorer) — exhaustive.
- **Integration:** `collect_settlements` against a `FakeProvider` scripted through
  kickoff → goal → goal → finish, asserting **exactly-once** messaging and that a simulated restart
  (re-running a cycle with the same provider state) produces **no** duplicate messages.
- All quality gates must pass: `ruff check`, `ruff format --check`, `mypy --strict`, `pytest -q`.

## Documentation (same change — project rule #3)

- `COMPLETION.md` §8.3 / §9.2 — document kickoff + goal notifications and the live-score detection
  mechanism.
- `/ajuda` text in `domain/text_pt.py` — add a line that the bot announces kickoff and every goal.

## Out of scope

- Half-time / full-time-whistle (non-result) notifications.
- Configurable per-notification channels or per-user opt-in beyond the existing role.
- Red cards, lineups, or other match events.
