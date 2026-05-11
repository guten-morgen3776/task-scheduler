"""Append-only behavior logging.

`record()` is intentionally never allowed to break the calling code: if the
insert fails for any reason it's logged and swallowed. The main API path
should never block on telemetry.
"""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_now
from app.models import EventLog

logger = logging.getLogger("app.event_log")


async def record(
    db: AsyncSession,
    user_id: str,
    event_type: str,
    *,
    subject_type: str | None = None,
    subject_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Append one row to event_log. Failures are swallowed."""
    try:
        db.add(
            EventLog(
                user_id=user_id,
                occurred_at=utc_now(),
                event_type=event_type,
                subject_type=subject_type,
                subject_id=subject_id,
                payload=payload or {},
            )
        )
        await db.flush()
    except Exception as e:  # noqa: BLE001 — telemetry never blocks the caller
        logger.warning(
            "event_log record failed (type=%s, subject=%s/%s): %s",
            event_type,
            subject_type,
            subject_id,
            e,
        )
