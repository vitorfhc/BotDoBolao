"""Pure unit tests for retry_async — no real sleeping or I/O (injected sleep + predicate)."""

from __future__ import annotations

import pytest

from tigrinho.providers.retry import retry_async


class _Boom(Exception):
    """Stand-in transient error."""


def _is_boom(exc: Exception) -> bool:
    return isinstance(exc, _Boom)


async def test_returns_immediately_on_success() -> None:
    calls = 0
    slept: list[float] = []

    async def call() -> str:
        nonlocal calls
        calls += 1
        return "ok"

    async def sleep(d: float) -> None:
        slept.append(d)

    result = await retry_async(
        call, retries=3, backoff_base=0.5, sleep=sleep, is_transient=_is_boom
    )
    assert result == "ok"
    assert calls == 1
    assert slept == []  # no retries, no sleeping


async def test_retries_transient_then_succeeds() -> None:
    calls = 0
    slept: list[float] = []

    async def call() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise _Boom
        return "ok"

    async def sleep(d: float) -> None:
        slept.append(d)

    result = await retry_async(
        call, retries=3, backoff_base=0.5, sleep=sleep, is_transient=_is_boom
    )
    assert result == "ok"
    assert calls == 3
    assert slept == [0.5, 1.0]  # exponential: 0.5*2**0, then 0.5*2**1


async def test_raises_after_exhausting_retries() -> None:
    calls = 0
    slept: list[float] = []

    async def call() -> str:
        nonlocal calls
        calls += 1
        raise _Boom

    async def sleep(d: float) -> None:
        slept.append(d)

    with pytest.raises(_Boom):
        await retry_async(call, retries=2, backoff_base=1.0, sleep=sleep, is_transient=_is_boom)
    assert calls == 3  # initial attempt + 2 retries
    assert slept == [1.0, 2.0]


async def test_does_not_retry_non_transient() -> None:
    calls = 0

    async def call() -> str:
        nonlocal calls
        calls += 1
        raise ValueError("nope")

    async def sleep(d: float) -> None:
        raise AssertionError("should not sleep on a non-transient error")

    with pytest.raises(ValueError):
        await retry_async(call, retries=3, backoff_base=0.5, sleep=sleep, is_transient=_is_boom)
    assert calls == 1  # not retried
