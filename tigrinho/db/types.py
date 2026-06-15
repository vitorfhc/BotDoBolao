"""Custom SQLAlchemy column types.

Grounded against the SQLAlchemy 2.0 "TypeDecorator" recipe:
https://docs.sqlalchemy.org/en/20/core/custom_types.html
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Dialect, TypeDecorator


class TZDateTime(TypeDecorator[datetime]):
    """Persist timezone-aware datetimes as naive UTC; return them as UTC-aware.

    SQLite has no native timezone support, so we normalize every value to UTC on the
    way in and re-attach UTC on the way out. Binding a naive datetime raises ``TypeError``
    (fail-fast): the whole app works in explicit UTC instants (COMPLETION.md §6).
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise TypeError("TZDateTime requires timezone-aware datetimes")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)
