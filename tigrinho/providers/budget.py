"""RequestBudget — hard daily ceiling on provider requests (COMPLETION.md §7.3).

Wrap every real provider call in :meth:`RequestBudget.run`. Before the call it reads today's
count (today = now in ``api_budget_reset_tz``); at or above ``api_daily_cap`` it raises
:class:`BudgetExceeded` and the call is skipped. Only a **successful** call increments the
counter. The counter resets automatically when the budget date rolls over (a new date key).

The clock is injected so callers/tests are deterministic; the DB write goes through the caller's
session (commit is the caller's responsibility).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, tzinfo
from typing import TypeVar

from tigrinho.db.repositories import ApiUsageRepository

T = TypeVar("T")


class BudgetExceeded(Exception):
    """Raised when the daily provider-request cap has been reached; the call is skipped."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


class RequestBudget:
    """Gate provider calls against a per-day request cap."""

    def __init__(
        self,
        usage: ApiUsageRepository,
        *,
        cap: int,
        reset_tz: tzinfo,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._usage = usage
        self._cap = cap
        self._reset_tz = reset_tz
        self._clock = clock

    def budget_date(self) -> date:
        """The current budget day (today in ``api_budget_reset_tz``)."""
        return self._clock().astimezone(self._reset_tz).date()

    def remaining(self) -> int:
        """Requests left in today's budget (never negative)."""
        return max(0, self._cap - self._usage.get_count(self.budget_date()))

    async def run(self, call: Callable[[], Awaitable[T]]) -> T:
        """Run ``call`` if budget remains, then increment; else raise :class:`BudgetExceeded`."""
        today = self.budget_date()
        if self._usage.get_count(today) >= self._cap:
            raise BudgetExceeded(f"daily API request cap reached ({self._cap}) for {today}")
        result = await call()
        self._usage.increment(today)
        return result
