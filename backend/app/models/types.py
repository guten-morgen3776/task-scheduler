from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """Datetime column that always stores UTC and returns tz-aware UTC.

    SQLite stores DateTime as naive TEXT, so SQLAlchemy returns a naive
    datetime even with timezone=True. This decorator:
      - rejects naive datetimes on write (forces explicit timezones)
      - converts incoming aware datetimes to UTC before storing
      - re-attaches UTC tzinfo when loading from the database
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(
        self, value: datetime | None, dialect: Any
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(
                "Naive datetime cannot be stored; pass a tz-aware datetime"
            )
        return value.astimezone(UTC)

    def process_result_value(
        self, value: datetime | None, dialect: Any
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
