"""Structured logging setup — structlog rendering to stdout. See COMPLETION.md §3, §14.

JSON output (default) for machine-readable container logs (``docker compose logs``), or a
human-friendly console renderer for local development. Configure once at startup via
:func:`configure_logging`, then obtain loggers with :func:`get_logger` and attach context
(fixture ids, counts, budget usage) as keyword arguments.

Grounded against structlog 26.1.0:
https://www.structlog.org/en/stable/getting-started.html
"""

from __future__ import annotations

import logging
from typing import cast

import structlog
from structlog.types import FilteringBoundLogger, Processor

from .config import LogFormat


def configure_logging(level: str, log_format: LogFormat) -> None:
    """Configure structlog globally to emit to stdout at ``level`` in ``log_format``.

    Unknown level names fall back to ``INFO`` (config already validates the value, this is
    just belt-and-braces). Idempotent: safe to call again to reconfigure.
    """
    level_int = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    if log_format is LogFormat.JSON:
        processors.append(structlog.processors.format_exc_info)
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.set_exc_info)
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level_int),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> FilteringBoundLogger:
    """Return a configured structlog logger (call :func:`configure_logging` first)."""
    if name is None:
        return cast(FilteringBoundLogger, structlog.get_logger())
    return cast(FilteringBoundLogger, structlog.get_logger(name))
