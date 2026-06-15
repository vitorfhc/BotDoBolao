"""retry_async — retry an async call on transient failures with exponential backoff.

Pure and deterministic: the caller injects ``sleep`` (tests pass a no-op recorder instead of
``asyncio.sleep``) and an ``is_transient`` predicate that decides which exceptions are worth
retrying. Nothing here knows about httpx — the predicate does (see ``api_football._is_transient``).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable


async def retry_async[T](
    call: Callable[[], Awaitable[T]],
    *,
    retries: int,
    backoff_base: float,
    sleep: Callable[[float], Awaitable[None]],
    is_transient: Callable[[Exception], bool],
) -> T:
    """Run ``call``; on a transient exception sleep ``backoff_base * 2**n`` and retry, up to
    ``retries`` extra attempts. A non-transient exception (or the final transient one once
    retries are exhausted) propagates unchanged.
    """
    attempt = 0
    while True:
        try:
            return await call()
        except Exception as exc:
            if attempt >= retries or not is_transient(exc):
                raise
            await sleep(backoff_base * 2.0**attempt)
            attempt += 1
