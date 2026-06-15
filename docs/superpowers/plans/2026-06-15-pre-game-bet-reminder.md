# Pre-Game Bet Reminder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Post a pre-game reminder to the announce channel ~1 hour before each match kicks off, pinging the `@Tigrinhos` role to tell people to place their bets before the opening whistle.

**Architecture:** A new DB-only `ReminderCog` runs a 1-minute `tasks.loop` that reads `games.kickoff_utc` (already stored by the daily sync) — **no API-Football calls**. A pure `select_due_reminders` filter picks games inside the lead window that have not been reminded; a pure `format_reminder_announcement` renders one combined pt-BR message. A new nullable `reminder_sent_at` column dedups (restart-safe). The channel is resolved **before** the dedup flag is committed, so a cold-cache miss retries instead of silently dropping the reminder.

**Tech Stack:** Python 3.12, discord.py (`commands.Cog`, `tasks.loop`, `discord.AllowedMentions`), SQLAlchemy 2.0 typed ORM, Alembic, pydantic-settings, pytest.

**Spec:** `docs/superpowers/specs/2026-06-15-pre-game-bet-reminder-design.md`

**Quality gate (must pass before every commit that touches code):**
```
uv run ruff check . && uv run ruff format --check . && uv run mypy --strict . && uv run pytest -q
```

---

## Task 1: Config setting `reminder_lead_minutes`

**Files:**
- Modify: `tigrinho/config.py` (add field next to the other optional ints, ~line 90)
- Modify: `config.example.yaml` (add key under the optional section)
- Modify: `COMPLETION.md` (§4 settings table)
- Test: `tests/test_config.py` (new test), `tests/test_config_example.py` (extend)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_reminder_lead_minutes_default_is_60() -> None:
    settings = Settings(
        discord_token="tok",
        api_football_key="key",
        guild_id=1,
        announce_channel_id=2,
        tigrinhos_role_id=3,
        admin_user_id=4,
    )
    assert settings.reminder_lead_minutes == 60


def test_reminder_lead_minutes_must_be_positive() -> None:
    import pytest

    with pytest.raises(Exception):  # pydantic ValidationError (gt=0)
        Settings(
            discord_token="tok",
            api_football_key="key",
            guild_id=1,
            announce_channel_id=2,
            tigrinhos_role_id=3,
            admin_user_id=4,
            reminder_lead_minutes=0,
        )
```

(If `tests/test_config.py` already imports `Settings`, reuse the existing import; otherwise add `from tigrinho.config import Settings` at the top.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_config.py::test_reminder_lead_minutes_default_is_60 -v`
Expected: FAIL — `Settings` has no field `reminder_lead_minutes` (and with `extra="forbid"` the second test errors on an unknown kwarg).

- [ ] **Step 3: Add the field**

In `tigrinho/config.py`, in the `# --- Settings: config.yaml (§4.2) ---` block, immediately after the `sync_time: str = "06:00"` line, add:

```python
    reminder_lead_minutes: int = Field(default=60, gt=0)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 5: Update `config.example.yaml`**

In `config.example.yaml`, immediately after the `sync_time: "06:00"` line, add:

```yaml
reminder_lead_minutes: 60              # minutes before kickoff to ping @Tigrinhos with a bet reminder
```

- [ ] **Step 6: Update the `config.example.yaml` completeness test**

In `tests/test_config_example.py`, add `"REMINDER_LEAD_MINUTES",` to the `_FIELD_ENV_VARS` list (so a stray env var can't mask the YAML key), and add this assertion at the end of `test_config_example_loads`:

```python
    assert settings.reminder_lead_minutes == 60
```

- [ ] **Step 7: Update `COMPLETION.md` §4 table**

In the settings table, immediately after the `sync_time` row, insert:

```markdown
| `reminder_lead_minutes` | no | `60` | Minutes before kickoff to ping `@Tigrinhos` with a "place your bets" reminder (§9.4). |
```

- [ ] **Step 8: Run the full config-related tests, then commit**

Run: `uv run pytest tests/test_config.py tests/test_config_example.py -q`
Expected: PASS.

```bash
git add tigrinho/config.py config.example.yaml COMPLETION.md tests/test_config.py tests/test_config_example.py
git commit -m "feat(config): add reminder_lead_minutes setting (default 60)"
```

---

## Task 2: Schema — `reminder_sent_at` column + Alembic migration

**Files:**
- Modify: `tigrinho/db/models.py:62-66` (Game dedup columns)
- Create: `tigrinho/db/migrations/versions/d2e4f6a8b0c1_pre_game_reminder_state.py`
- Test: `tests/test_migrations.py` (existing `test_migrated_schema_matches_models` enforces model↔migration parity)

Note: in-memory test DBs use `Base.metadata.create_all`, so the new column appears automatically there. `_game_from_fixture` needs **no** change — like `kickoff_announced_at`, the column relies on the ORM nullable default at insert.

- [ ] **Step 1: Add the column to the model (this is the "failing test" trigger)**

In `tigrinho/db/models.py`, in the `Game` class, immediately after the `kickoff_announced_at: Mapped[datetime | None]` line, add:

```python
    reminder_sent_at: Mapped[datetime | None]
```

- [ ] **Step 2: Run the migration parity test to verify it fails**

Run: `uv run pytest tests/test_migrations.py::test_migrated_schema_matches_models -v`
Expected: FAIL — `compare_metadata` reports an `add_column` diff for `games.reminder_sent_at` (model has it, migrations don't).

- [ ] **Step 3: Create the migration**

Create `tigrinho/db/migrations/versions/d2e4f6a8b0c1_pre_game_reminder_state.py`:

```python
"""pre-game reminder state

Revision ID: d2e4f6a8b0c1
Revises: b7c3f1a9d2e4
Create Date: 2026-06-15 18:30:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2e4f6a8b0c1"
down_revision: str | Sequence[str] | None = "b7c3f1a9d2e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("games", sa.Column("reminder_sent_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("games", "reminder_sent_at")
```

- [ ] **Step 4: Run the migration tests to verify they pass**

Run: `uv run pytest tests/test_migrations.py -q`
Expected: PASS (parity restored; upgrade/downgrade still work).

- [ ] **Step 5: Commit**

```bash
git add tigrinho/db/models.py tigrinho/db/migrations/versions/d2e4f6a8b0c1_pre_game_reminder_state.py
git commit -m "feat(db): add games.reminder_sent_at column + migration"
```

---

## Task 3: Pure `select_due_reminders`

**Files:**
- Create: `tigrinho/bot/reminder_cog.py`
- Test: `tests/test_reminder_logic.py`

`select_due_reminders` operates on `Game` rows (DB models, no Discord) so it stays pure and unit-testable. It keeps a game iff it has no `reminder_sent_at` and `now` is inside `[kickoff - lead, kickoff)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_reminder_logic.py`:

```python
"""Pure tests for pre-game reminder selection + rendering (COMPLETION.md §9.4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tigrinho.bot.reminder_cog import select_due_reminders
from tigrinho.db.models import Game

NOW = datetime(2026, 6, 15, 18, 0, tzinfo=UTC)


def _game(fid: int, *, kickoff: datetime, reminder_sent_at: datetime | None = None) -> Game:
    return Game(
        fixture_id=fid,
        home_team_name="Brasil",
        away_team_name="Argentina",
        kickoff_utc=kickoff,
        kickoff_local=kickoff,
        reminder_sent_at=reminder_sent_at,
    )


def test_due_when_inside_lead_window() -> None:
    game = _game(1, kickoff=NOW + timedelta(minutes=30))
    assert select_due_reminders([game], now=NOW, lead_minutes=60) == [game]


def test_due_exactly_at_lead_edge() -> None:
    game = _game(1, kickoff=NOW + timedelta(minutes=60))
    assert select_due_reminders([game], now=NOW, lead_minutes=60) == [game]


def test_not_due_before_window() -> None:
    game = _game(1, kickoff=NOW + timedelta(minutes=61))
    assert select_due_reminders([game], now=NOW, lead_minutes=60) == []


def test_not_due_at_or_after_kickoff() -> None:
    game = _game(1, kickoff=NOW)
    assert select_due_reminders([game], now=NOW, lead_minutes=60) == []


def test_not_due_when_already_reminded() -> None:
    game = _game(1, kickoff=NOW + timedelta(minutes=30), reminder_sent_at=NOW)
    assert select_due_reminders([game], now=NOW, lead_minutes=60) == []


def test_fires_late_after_downtime_while_still_before_kickoff() -> None:
    # Bot was offline at kickoff-60; it's now kickoff-10, still before kickoff -> still due.
    game = _game(1, kickoff=NOW + timedelta(minutes=10))
    assert select_due_reminders([game], now=NOW, lead_minutes=60) == [game]


def test_preserves_input_order() -> None:
    g1 = _game(1, kickoff=NOW + timedelta(minutes=10))
    g2 = _game(2, kickoff=NOW + timedelta(minutes=20))
    assert select_due_reminders([g1, g2], now=NOW, lead_minutes=60) == [g1, g2]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_reminder_logic.py -v`
Expected: FAIL — `ModuleNotFoundError: tigrinho.bot.reminder_cog`.

- [ ] **Step 3: Create the module with the pure selector**

Create `tigrinho/bot/reminder_cog.py`:

```python
"""Pre-game bet reminder (COMPLETION.md §9.4).

A DB-only reminder: shortly before each kickoff it posts one combined pt-BR message to the announce
channel pinging ``@Tigrinhos`` to place bets (which close at the opening whistle). It reads
``games.kickoff_utc`` (stored by the daily sync) and never calls the provider. The pure
:func:`select_due_reminders` / :func:`format_reminder_announcement` are kept Discord-free and
unit-tested; the :class:`ReminderCog` (``tasks.loop`` + send) is layered on top.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from tigrinho.db.models import Game


def select_due_reminders(
    games: Sequence[Game], *, now: datetime, lead_minutes: int
) -> list[Game]:
    """Games whose reminder is due this tick: not yet reminded and ``now`` is inside
    ``[kickoff - lead, kickoff)``. The upper bound (``now < kickoff``) is what makes a reminder
    "fire late" after downtime yet never fire once bets have closed. Input order is preserved
    (callers pass ``GameRepository.list_open(now)``, already ordered by kickoff)."""
    lead = timedelta(minutes=lead_minutes)
    return [
        game
        for game in games
        if game.reminder_sent_at is None and game.kickoff_utc - lead <= now < game.kickoff_utc
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_reminder_logic.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tigrinho/bot/reminder_cog.py tests/test_reminder_logic.py
git commit -m "feat(reminder): pure select_due_reminders window filter"
```

---

## Task 4: Pure `format_reminder_announcement`

**Files:**
- Modify: `tigrinho/bot/reminder_cog.py` (add the renderer)
- Test: `tests/test_reminder_logic.py` (add render tests)

Reuses `format_kickoff_pt` from `sync_planning` (DRY) for the `Sáb 16/06 16:00` kickoff format. The header is game-count-agnostic, so one renderer covers single and multiple games (bullets handle plurality).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_reminder_logic.py`:

```python
from tigrinho.bot.reminder_cog import format_reminder_announcement  # noqa: E402

SAO_PAULO = __import__("zoneinfo").ZoneInfo("America/Sao_Paulo")


def test_format_single_game_has_ping_and_kickoff_and_apostar() -> None:
    game = _game(1, kickoff=datetime(2026, 6, 16, 19, 0, tzinfo=UTC))
    msg = format_reminder_announcement([game], role_mention="<@&333>", tz=SAO_PAULO)
    assert "<@&333>" in msg
    assert "Brasil x Argentina" in msg
    assert "/apostar" in msg
    assert "16/06 16:00" in msg  # 19:00 UTC -> 16:00 America/Sao_Paulo


def test_format_multiple_games_lists_each_with_one_header() -> None:
    g1 = _game(1, kickoff=datetime(2026, 6, 16, 19, 0, tzinfo=UTC))
    g2 = _game(2, kickoff=datetime(2026, 6, 16, 22, 0, tzinfo=UTC))
    msg = format_reminder_announcement([g1, g2], role_mention="<@&333>", tz=SAO_PAULO)
    assert msg.count("<@&333>") == 1  # one ping for the whole batch
    assert msg.count("Brasil x Argentina") == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_reminder_logic.py::test_format_single_game_has_ping_and_kickoff_and_apostar -v`
Expected: FAIL — `ImportError: cannot import name 'format_reminder_announcement'`.

- [ ] **Step 3: Add the renderer**

In `tigrinho/bot/reminder_cog.py`, add `from datetime import datetime, timedelta, tzinfo` (extend the existing import to include `tzinfo`), add `from .sync_planning import format_kickoff_pt`, and append:

```python
def format_reminder_announcement(
    games: Sequence[Game], *, role_mention: str, tz: tzinfo
) -> str:
    """One combined pt-BR reminder for all due games, pinging the role once (§9.4). No hardcoded
    lead minutes — the actual lead varies (fire-late), so the header is time-agnostic."""
    lines = [f"⏰ **Já vai começar!** As apostas fecham no apito inicial. {role_mention}"]
    lines += [
        f"• {game.home_team_name} x {game.away_team_name} — "
        f"{format_kickoff_pt(game.kickoff_utc.astimezone(tz))}"
        for game in games
    ]
    lines.append("Corra para apostar com /apostar! 🐯")
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_reminder_logic.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tigrinho/bot/reminder_cog.py tests/test_reminder_logic.py
git commit -m "feat(reminder): pure format_reminder_announcement (combined, one ping)"
```

---

## Task 5: `ReminderCog` + registration

**Files:**
- Modify: `tigrinho/bot/reminder_cog.py` (add the cog)
- Modify: `tigrinho/bot/client.py` (import + register in the `session_factory` block)
- Modify: `tests/test_composition.py:17` (add `ReminderCog` to `ALL_COGS`)
- Test: `tests/test_reminder_cog.py`

The cog resolves the channel **after** computing due games but **before** committing `reminder_sent_at`, so a cold/unavailable channel returns without marking and the next tick retries.

- [ ] **Step 1: Write the failing cog tests**

Create `tests/test_reminder_cog.py`:

```python
"""Tests for ReminderCog wiring + run_reminders (COMPLETION.md §9.4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import discord
from discord.ext import tasks

from tigrinho.bot.client import TigrinhoBot
from tigrinho.bot.reminder_cog import ReminderCog
from tigrinho.config import Settings
from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import Base, Game
from tigrinho.db.repositories import GameRepository

NOW = datetime(2026, 6, 15, 18, 0, tzinfo=UTC)


def _settings() -> Settings:
    return Settings(
        discord_token="tok",
        api_football_key="key",
        guild_id=111,
        announce_channel_id=222,
        tigrinhos_role_id=333,
        admin_user_id=444,
    )


class _StubChannel(discord.abc.Messageable):
    def __init__(self, sink: list[tuple[str, discord.AllowedMentions]]) -> None:
        self._sink = sink

    async def _get_channel(self) -> discord.abc.MessageableChannel:
        raise NotImplementedError

    async def send(  # type: ignore[override]
        self, content: str, *, allowed_mentions: discord.AllowedMentions
    ) -> None:
        self._sink.append((content, allowed_mentions))


def _add_game(factory: object, *, kickoff: datetime) -> None:
    with factory() as session:  # type: ignore[operator]
        session.add(
            Game(
                fixture_id=1,
                match_hash="h1",
                stage="GROUP",
                home_team_id=10,
                home_team_name="Brasil",
                away_team_id=20,
                away_team_name="Argentina",
                kickoff_utc=kickoff,
                kickoff_local=kickoff,
                status="SCHEDULED",
                home_goals_90=None,
                away_goals_90=None,
                advancing_team_id=None,
                announced_at=None,
                kickoff_announced_at=None,
                last_announced_home_goals=None,
                last_announced_away_goals=None,
                settled_at=None,
                reminder_sent_at=None,
            )
        )
        session.commit()


async def test_reminder_cog_constructs(tmp_path: Path) -> None:
    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    bot = TigrinhoBot(_settings())
    try:
        cog = ReminderCog(
            bot,
            settings=_settings(),
            session_factory=create_session_factory(engine),
            clock=lambda: NOW,
        )
        assert isinstance(cog.reminders, tasks.Loop)
        assert cog.reminders.is_running() is False
    finally:
        await bot.close()


async def test_run_reminders_pings_role_marks_sent_and_is_idempotent(tmp_path: Path) -> None:
    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    _add_game(factory, kickoff=NOW + timedelta(minutes=30))  # inside 60-min lead window

    sent: list[tuple[str, discord.AllowedMentions]] = []
    bot = TigrinhoBot(_settings())
    try:
        cog = ReminderCog(
            bot, settings=_settings(), session_factory=factory, clock=lambda: NOW
        )
        bot.get_channel = lambda _id: _StubChannel(sent)  # type: ignore[method-assign,assignment,return-value]
        await cog.run_reminders()
        await cog.run_reminders()  # second tick: already reminded -> nothing
    finally:
        await bot.close()

    assert len(sent) == 1
    content, am = sent[0]
    assert "<@&333>" in content and "/apostar" in content
    assert am.roles is True
    with factory() as session:
        game = GameRepository(session).get(1)
        assert game is not None and game.reminder_sent_at is not None


async def test_run_reminders_does_not_mark_when_channel_unavailable(tmp_path: Path) -> None:
    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    _add_game(factory, kickoff=NOW + timedelta(minutes=30))

    sent: list[tuple[str, discord.AllowedMentions]] = []
    bot = TigrinhoBot(_settings())
    try:
        cog = ReminderCog(
            bot, settings=_settings(), session_factory=factory, clock=lambda: NOW
        )
        bot.get_channel = lambda _id: None  # type: ignore[method-assign,assignment,return-value]
        await cog.run_reminders()  # channel cold -> skip without marking
        with factory() as session:
            game = GameRepository(session).get(1)
            assert game is not None and game.reminder_sent_at is None
        # Channel becomes available -> next tick fires.
        bot.get_channel = lambda _id: _StubChannel(sent)  # type: ignore[method-assign,assignment,return-value]
        await cog.run_reminders()
    finally:
        await bot.close()

    assert len(sent) == 1


async def test_run_reminders_skips_game_not_yet_in_window(tmp_path: Path) -> None:
    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    _add_game(factory, kickoff=NOW + timedelta(minutes=90))  # outside 60-min lead window

    sent: list[tuple[str, discord.AllowedMentions]] = []
    bot = TigrinhoBot(_settings())
    try:
        cog = ReminderCog(
            bot, settings=_settings(), session_factory=factory, clock=lambda: NOW
        )
        bot.get_channel = lambda _id: _StubChannel(sent)  # type: ignore[method-assign,assignment,return-value]
        await cog.run_reminders()
    finally:
        await bot.close()

    assert sent == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_reminder_cog.py -v`
Expected: FAIL — `ImportError: cannot import name 'ReminderCog'`.

- [ ] **Step 3: Add the cog to `reminder_cog.py`**

At the top of `tigrinho/bot/reminder_cog.py`, extend the imports:

```python
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta, tzinfo

import discord
from discord.ext import commands, tasks
from sqlalchemy.orm import Session

from tigrinho.config import Settings
from tigrinho.db.models import Game
from tigrinho.db.repositories import GameRepository
from tigrinho.logging import get_logger

from .sync_planning import format_kickoff_pt

log = get_logger("tigrinho.bot.reminder")


def _utcnow() -> datetime:
    return datetime.now(UTC)
```

Then append the cog class at the end of the file:

```python
class ReminderCog(commands.Cog):
    """Pre-game bet reminder loop (COMPLETION.md §9.4). DB-only — no provider."""

    def __init__(
        self,
        bot: commands.Bot,
        *,
        settings: Settings,
        session_factory: Callable[[], Session],
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.bot = bot
        self.settings = settings
        self.session_factory = session_factory
        self._clock = clock

    async def cog_load(self) -> None:
        self.reminders.start()

    async def cog_unload(self) -> None:
        self.reminders.cancel()

    @tasks.loop(minutes=1)
    async def reminders(self) -> None:
        try:
            await self.run_reminders()
        except Exception:
            log.exception("reminders_failed")

    @reminders.before_loop
    async def _before_reminders(self) -> None:
        await self.bot.wait_until_ready()

    async def run_reminders(self) -> None:
        """Post one combined pre-game reminder (pinging the role) for every game whose lead window
        has opened and that hasn't been reminded. Resolve the channel BEFORE committing the dedup
        flag: if it's unavailable (e.g. cold cache after a restart), skip without marking so the
        next tick retries — here the message *is* the feature (§9.4)."""
        now = self._clock()
        with self.session_factory() as session:
            due = select_due_reminders(
                GameRepository(session).list_open(now),
                now=now,
                lead_minutes=self.settings.reminder_lead_minutes,
            )
            if not due:
                return
            channel = self._get_announce_channel()
            if channel is None:
                return  # cold/unavailable channel -> do not mark; retry next tick
            message = format_reminder_announcement(
                due,
                role_mention=f"<@&{self.settings.tigrinhos_role_id}>",
                tz=self.settings.tzinfo,
            )
            for game in due:
                game.reminder_sent_at = now
            session.commit()
        await channel.send(message, allowed_mentions=discord.AllowedMentions(roles=True))

    def _get_announce_channel(self) -> discord.abc.Messageable | None:
        channel = self.bot.get_channel(self.settings.announce_channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            log.warning(
                "announce_channel_unavailable", channel_id=self.settings.announce_channel_id
            )
            return None
        return channel
```

Note: remove the now-duplicated narrow import line from Task 3/4 — the file should have a single import block. After editing, the top of the file imports `Callable, Sequence` from `collections.abc` and `UTC, datetime, timedelta, tzinfo` from `datetime` (the pure functions still use `timedelta`/`tzinfo`/`Sequence`/`Game`).

- [ ] **Step 4: Register the cog in `client.py`**

In `tigrinho/bot/client.py`, add the import near the other cog imports (after `from .poll_cog import PollCog`):

```python
from .reminder_cog import ReminderCog
```

Then in `_register_cogs`, inside the `if self.session_factory is not None:` block, immediately after the `BoardCog` `add_cog(...)` call and **before** `if self.provider_factory is not None:`, add:

```python
            await self.add_cog(
                ReminderCog(
                    self,
                    settings=self.settings,
                    session_factory=self.session_factory,
                )
            )
```

- [ ] **Step 5: Add `ReminderCog` to the composition test**

In `tests/test_composition.py`, change line 17 to include `ReminderCog`:

```python
ALL_COGS = {"HelpCog", "SubscribeCog", "BetsCog", "BoardCog", "SyncCog", "PollCog", "ReminderCog"}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_reminder_cog.py tests/test_composition.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tigrinho/bot/reminder_cog.py tigrinho/bot/client.py tests/test_reminder_cog.py tests/test_composition.py
git commit -m "feat(reminder): ReminderCog loop + registration (channel-safe commit ordering)"
```

---

## Task 6: Reset `reminder_sent_at` on reschedule

**Files:**
- Modify: `tigrinho/bot/sync_cog.py` (`apply_plan` rescheduled branch, ~lines 87-95)
- Test: `tests/test_sync_apply.py` (add a test)

So a rescheduled game earns a fresh reminder for its new time (subject to the once-daily sync lag documented in the spec §6).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_sync_apply.py` (match the file's existing import/fixture style; it already builds a `Session` and uses `apply_plan`, `SyncPlan`, `GameRepository`, and a `Fixture` helper — reuse them. If a `_fixture(...)` helper isn't present, construct a `Fixture` inline as in `tests/test_sync_cog.py`):

```python
def test_reschedule_clears_reminder_sent_at(session: Session) -> None:
    from datetime import UTC, datetime, timedelta

    from tigrinho.bot.sync_cog import apply_plan
    from tigrinho.bot.sync_planning import SyncPlan
    from tigrinho.db.repositories import GameRepository
    from tigrinho.providers.base import Fixture, GameStatus, Stage

    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    kick = datetime(2026, 6, 15, 19, 0, tzinfo=UTC)
    tz = UTC

    def _fx(kickoff: datetime) -> Fixture:
        return Fixture(
            fixture_id=1,
            stage=Stage.GROUP,
            home_team_id=10,
            home_team_name="Brasil",
            away_team_id=20,
            away_team_name="Argentina",
            kickoff_utc=kickoff,
            status=GameStatus.SCHEDULED,
        )

    # Insert the game, then mark it as already reminded.
    apply_plan(session, SyncPlan(new=[_fx(kick)], rescheduled=[], voided=[]), now=now, tz=tz)
    game = GameRepository(session).get(1)
    assert game is not None
    game.reminder_sent_at = now
    session.flush()

    # Reschedule it -> reminder_sent_at must be cleared.
    later = kick + timedelta(hours=2)
    apply_plan(session, SyncPlan(new=[], rescheduled=[_fx(later)], voided=[]), now=now, tz=tz)
    game = GameRepository(session).get(1)
    assert game is not None
    assert game.kickoff_utc == later
    assert game.reminder_sent_at is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_sync_apply.py::test_reschedule_clears_reminder_sent_at -v`
Expected: FAIL — `reminder_sent_at` is still set (not reset on reschedule).

- [ ] **Step 3: Reset the flag in `apply_plan`**

In `tigrinho/bot/sync_cog.py`, in the `for fixture in plan.rescheduled:` loop, inside the `if game is not None:` block, after the `game.status = GameStatus.SCHEDULED.value` line, add:

```python
            game.reminder_sent_at = None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_sync_apply.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tigrinho/bot/sync_cog.py tests/test_sync_apply.py
git commit -m "feat(sync): clear reminder_sent_at on reschedule (fresh reminder for new time)"
```

---

## Task 7: Documentation — `/ajuda` + `COMPLETION.md` §9.4

**Files:**
- Modify: `tigrinho/domain/text_pt.py` (`help_text()` Avisos section, ~lines 157-160)
- Modify: `COMPLETION.md` (new §9.4 after §9.3)
- Test: `tests/test_text_pt.py` (add an assertion)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_text_pt.py`:

```python
def test_help_mentions_pre_game_reminder() -> None:
    text = help_text().lower()
    assert "lembr" in text  # e.g. "lembrando"/"lembrete"
    assert "antes" in text  # before kickoff
```

(Reuse the existing `from tigrinho.domain.text_pt import help_text` import at the top of the file.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_text_pt.py::test_help_mentions_pre_game_reminder -v`
Expected: FAIL — `/ajuda` doesn't yet mention the reminder.

- [ ] **Step 3: Update the `/ajuda` Avisos section**

In `tigrinho/domain/text_pt.py`, in `help_text()`, replace the Avisos paragraph (the string starting `"O cargo **@Tigrinhos** serve só para receber as menções..."`) so the block reads:

```python
        "**🔔 Avisos (cargo @Tigrinhos)**",
        "O cargo **@Tigrinhos** serve só para receber as menções nos anúncios — **qualquer pessoa "
        "pode apostar**, com ou sem o cargo. Use **/inscrever** para receber os avisos e **/sair** "
        "para parar.",
        "Pouco **antes** de cada jogo, o bot marca o **@Tigrinhos** lembrando que a bola vai rolar "
        "e que é hora de apostar — as apostas fecham no apito inicial.",
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_text_pt.py -q`
Expected: PASS (including `test_help_fits_discord_embed_description_limit`).

- [ ] **Step 5: Add `COMPLETION.md` §9.4**

In `COMPLETION.md`, immediately after the end of §9.3 (the line `Both are restart-safe and idempotent (dedup state persists on the game row).`) and before the `---` that precedes `## 10`, insert:

```markdown
### 9.4 Pre-game reminder (`reminder_lead_minutes`, default 60)

A separate `tasks.loop(minutes=1)` (`ReminderCog`) — **DB-only, no provider call**. Each tick it
selects open games (`list_open`) whose kickoff is within `reminder_lead_minutes` and that haven't
been reminded (`games.reminder_sent_at is None`), and posts **one consolidated** pt-BR message to
`announce_channel_id` **pinging `@Tigrinhos`** to place bets before the opening whistle.

- **Window:** a game is due when `now` is in `[kickoff - reminder_lead_minutes, kickoff)`. The upper
  bound means a reminder still **fires late** (e.g. after a restart) as long as bets are open, and
  never fires once the game has kicked off.
- **Channel-safe:** the channel is resolved **before** `reminder_sent_at` is committed; if it's
  unavailable (cold cache after a restart) the tick skips without marking, so the next tick retries
  (the reminder *is* the feature, unlike the cosmetic kickoff/goal messages).
- **Reschedule:** `apply_plan` clears `reminder_sent_at` so a moved game is reminded again — subject
  to the once-daily sync detection lag (a *sooner* reschedule landing inside the lead window before
  the next sync won't be re-reminded; same lag as the §9.1 re-announcement).

Restart-safe and idempotent (dedup state persists on the game row).
```

- [ ] **Step 6: Commit**

```bash
git add tigrinho/domain/text_pt.py COMPLETION.md tests/test_text_pt.py
git commit -m "docs: /ajuda + COMPLETION §9.4 for pre-game reminder"
```

---

## Task 8: Full quality gate

**Files:** none (verification only)

- [ ] **Step 1: Run the complete quality gate**

Run:
```
uv run ruff check . && uv run ruff format --check . && uv run mypy --strict . && uv run pytest -q
```
Expected: all green. If `ruff format --check` reports diffs, run `uv run ruff format .`, review, and amend the relevant commit.

- [ ] **Step 2: Confirm no regressions in adjacent suites**

Run: `uv run pytest tests/test_poll_cog.py tests/test_sync_cog.py tests/test_db.py tests/test_repositories.py -q`
Expected: PASS (the new nullable column and cog don't disturb existing flows).

---

## Self-Review

**Spec coverage:**
- §Schema (`reminder_sent_at` + migration, no `_game_from_fixture` change) → Task 2.
- §Config (`reminder_lead_minutes`, `>0`, example + §4 table) → Task 1.
- §Reschedule reset (`apply_plan`) → Task 6.
- §Pure logic (`select_due_reminders`, `format_reminder_announcement`) → Tasks 3, 4.
- §Cog + wiring (1-min loop, resolve-channel-before-commit, registered without provider) → Task 5.
- §Message copy (pt-BR, no hardcoded minutes, one ping) → Task 4.
- §Edge cases (fire-late, not-yet-in-window, already-reminded, channel-unavailable retry, reschedule) → Tasks 3, 5, 6 tests.
- §Docs (/ajuda + COMPLETION §9.4) → Task 7.
- §Testing (pure boundaries, DB/integration idempotency + channel-unavailable, reschedule, migration, config) → Tasks 1-7.

**Placeholder scan:** none — every code/test step shows complete content.

**Type/name consistency:** `select_due_reminders(games, *, now, lead_minutes) -> list[Game]` and `format_reminder_announcement(games, *, role_mention, tz) -> str` are used identically in Tasks 3-5; `ReminderCog(bot, *, settings, session_factory, clock=_utcnow)` matches its construction in `client.py` (Task 5) and the tests; the loop attribute is `reminders` everywhere; `reminder_sent_at` / `reminder_lead_minutes` spelled consistently across model, config, cog, sync, and docs.
