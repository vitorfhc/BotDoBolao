"""Tests for RequestBudget — the per-day provider-request hard-stop (COMPLETION.md §7.3)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from tigrinho.db.engine import create_db_engine, create_session_factory
from tigrinho.db.models import Base
from tigrinho.db.repositories import ApiUsageRepository
from tigrinho.providers.budget import BudgetExceeded, RequestBudget


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = create_db_engine(str(tmp_path / "t.db"))
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with factory() as s:
        yield s


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


async def test_run_under_cap_calls_and_increments(session: Session) -> None:
    usage = ApiUsageRepository(session)
    clock = _Clock(datetime(2026, 6, 15, 12, 0, tzinfo=UTC))
    budget = RequestBudget(usage, cap=5, reset_tz=UTC, clock=clock)

    called = False

    async def call() -> str:
        nonlocal called
        called = True
        return "ok"

    result = await budget.run(call)
    assert result == "ok"
    assert called is True
    assert usage.get_count(clock.now.date()) == 1


async def test_run_at_cap_raises_and_does_not_call(session: Session) -> None:
    usage = ApiUsageRepository(session)
    clock = _Clock(datetime(2026, 6, 15, 12, 0, tzinfo=UTC))
    for _ in range(5):
        usage.increment(clock.now.date())  # reach cap
    budget = RequestBudget(usage, cap=5, reset_tz=UTC, clock=clock)

    called = False

    async def call() -> str:
        nonlocal called
        called = True
        return "ok"

    with pytest.raises(BudgetExceeded):
        await budget.run(call)
    assert called is False  # request was skipped
    assert usage.get_count(clock.now.date()) == 5  # unchanged


async def test_failed_call_does_not_increment(session: Session) -> None:
    usage = ApiUsageRepository(session)
    clock = _Clock(datetime(2026, 6, 15, 12, 0, tzinfo=UTC))
    budget = RequestBudget(usage, cap=5, reset_tz=UTC, clock=clock)

    async def call() -> str:
        raise ValueError("network boom")

    with pytest.raises(ValueError, match="network boom"):
        await budget.run(call)
    assert usage.get_count(clock.now.date()) == 0  # nothing consumed


async def test_budget_date_uses_reset_timezone(session: Session) -> None:
    usage = ApiUsageRepository(session)
    # 02:30 UTC on the 16th == 23:30 on the 15th in America/Sao_Paulo (UTC-3).
    clock = _Clock(datetime(2026, 6, 16, 2, 30, tzinfo=UTC))
    sao_paulo = ZoneInfo("America/Sao_Paulo")

    utc_budget = RequestBudget(usage, cap=5, reset_tz=UTC, clock=clock)
    sp_budget = RequestBudget(usage, cap=5, reset_tz=sao_paulo, clock=clock)
    assert utc_budget.budget_date().day == 16
    assert sp_budget.budget_date().day == 15


async def test_counter_resets_across_days(session: Session) -> None:
    usage = ApiUsageRepository(session)
    clock = _Clock(datetime(2026, 6, 15, 12, 0, tzinfo=UTC))
    budget = RequestBudget(usage, cap=5, reset_tz=UTC, clock=clock)

    async def call() -> int:
        return 1

    await budget.run(call)
    assert usage.get_count(datetime(2026, 6, 15, tzinfo=UTC).date()) == 1
    clock.now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)  # roll over to next day
    assert budget.remaining() == 5  # fresh day
    await budget.run(call)
    assert usage.get_count(datetime(2026, 6, 16, tzinfo=UTC).date()) == 1
    assert usage.get_count(datetime(2026, 6, 15, tzinfo=UTC).date()) == 1  # prior day kept


async def test_remaining_never_negative(session: Session) -> None:
    usage = ApiUsageRepository(session)
    clock = _Clock(datetime(2026, 6, 15, 12, 0, tzinfo=UTC))
    for _ in range(7):
        usage.increment(clock.now.date())  # exceed cap of 5
    budget = RequestBudget(usage, cap=5, reset_tz=UTC, clock=clock)
    assert budget.remaining() == 0
