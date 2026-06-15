# Design: show team names instead of "Mandante/Visitante"

Date: 2026-06-15
Status: approved

## Problem

In the `/apostar` flow and the bet listings the bot labels the two sides of a
match generically as **Mandante** (home) and **Visitante** (away). Bettors can't
tell *who* they are voting for — they want to see the actual team name
(e.g. `Brasil`, `Argentina`).

## Principle

The change is **purely presentational**. The stored bet payloads
(`WinnerSelection.HOME/DRAW/AWAY`, the BTTS selections, exact-score integers)
and every grading / scoring / settlement / DB code path are **untouched**. We
only change displayed labels, threading the team names that the flow already
has on hand (`game.home_team_name` / `game.away_team_name`).

`/ajuda` stays generic — it describes the rules with no specific game, so
"mandante/visitante" remain correct there. `COMPLETION.md` does not pin any of
these label strings, so the spec needs no text change.

## User-facing spots changed

1. `/apostar` → **Vencedor** select: `Brasil / Empate / Argentina`
2. `/apostar` → **Ambos marcam** select: `Sim (ambos) / Só Brasil / Só Argentina / Nenhum`
3. `/apostar` → **Placar exato** modal fields: `Gols: Brasil` / `Gols: Argentina`
4. Confirmation message after betting (`render_payload`)
5. `/minhas_apostas` listing (`render_payload`)

### Portuguese phrasing

Team/country names have a gender the bot can't know, so the masculine articles
in "Só **o** mandante" / "Gols **do** mandante" would be wrong for "Só **a**
França". Phrasing therefore **drops the article**: `Só Brasil`, `Só França`,
`Gols: Brasil` — natural and correct for any name.

## Components

### `Matchup` value object (`tigrinho/bot/apostar_view.py`)

The place-bet flow currently passes a bare `matchup` string and separately
re-derives `f"{home} x {away}"` in several places. Replace the `matchup: str`
parameter *in the place-bet flow* with a small frozen dataclass bundling the
three facts that always travel together:

```python
@dataclass(frozen=True, slots=True)
class Matchup:
    home_name: str
    away_name: str
    def __str__(self) -> str:
        return f"{self.home_name} x {self.away_name}"
```

Display sites (`f"**{matchup}** — ..."`) keep working via `__str__`; the
WINNER/BTTS/modal sites read `matchup.home_name` / `matchup.away_name`.
`games_to_choices` builds the `Matchup` from the `Game`. The delete flow's
`OpenBetChoice.matchup` and the listing `MyBetLine.matchup` stay plain display
strings (they never need splitting).

### Domain text (`tigrinho/domain/text_pt.py`)

Add two pure helpers; keep the existing `WINNER_LABELS_PT` / `BTTS_LABELS_PT`
dicts as the generic fallback:

- `winner_label(sel, *, home_name=None, away_name=None)` → `home_name` /
  `"Empate"` / `away_name`; falls back to the dict when names are absent.
- `btts_label(sel, *, home_name=None, away_name=None)` → `f"Só {home_name}"` /
  `f"Só {away_name}"` for the single-team options; `"Sim (ambos)"` / `"Nenhum"`
  unchanged; generic fallback when names absent.
- `render_payload(...)` gains optional `home_name` / `away_name`, routing
  Winner/BTTS payloads through the two helpers. No-name callers keep today's
  generic output (back-compat for existing domain tests).

### UI wiring (`tigrinho/bot/apostar_view.py`)

- `build_value_view` WINNER/BTTS options use `winner_label` / `btts_label`.
- `ScoreModal` field labels become `f"Gols: {home_name}"[:45]` /
  `f"Gols: {away_name}"[:45]` (Discord caps modal labels at 45 chars).
- `_finalize_bet` passes the names into `render_payload`.

### Listings (`tigrinho/bot/bets_cog.py`)

`build_my_bet_lines` already holds the `Game`, so it passes
`home_team_name` / `away_team_name` into `render_payload`.

## Testing (TDD — tests written first)

- `tests/test_text_pt.py`: `winner_label` / `btts_label` with and without names
  (names present → team name / `Só {name}`; absent → generic fallback).
- `tests/test_render_payload.py`: render Winner/BTTS with names (→ team name /
  `Só {name}`) and without (→ generic, back-compat).
- `tests/test_apostar_view.py`: `Matchup.__str__`; `games_to_choices` carries
  names; `build_value_view` WINNER/BTTS option labels; `ScoreModal` field
  labels include the team name.
- `tests/test_bets_cog.py`: a WINNER/BTTS bet in `build_my_bet_lines` renders
  the team name.

Then the full gate must pass:
`uv run ruff check . && uv run ruff format --check . && uv run mypy --strict . && uv run pytest -q`

## Out of scope / unchanged

- Grading, scoring, settlement, DB schema, stored payloads.
- `/ajuda` text and `COMPLETION.md` (no pinned labels; rules unchanged).
- `OVER_UNDER` labels (no team reference).
- The delete flow (`OpenBetChoice`) — no per-team labels there.
