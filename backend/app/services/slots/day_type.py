import re
from datetime import date

from app.schemas.calendar import CalendarEvent
from app.schemas.settings import (
    WEEKDAYS,
    DayTypeCondition,
    DayTypeDefault,
    DayTypeRule,
)
from app.services.slots.domain import DayTypeResult


def _matches(
    cond: DayTypeCondition,
    target_date: date,
    events: list[CalendarEvent],
    busy_hours: float,
) -> bool:
    if cond.weekday is not None:
        weekday_name = WEEKDAYS[target_date.weekday()]
        if cond.weekday != weekday_name:
            return False

    count = len(events)
    if cond.event_count_min is not None and count < cond.event_count_min:
        return False
    if cond.event_count_max is not None and count > cond.event_count_max:
        return False

    if cond.total_busy_hours_min is not None and busy_hours < cond.total_busy_hours_min:
        return False
    if cond.total_busy_hours_max is not None and busy_hours > cond.total_busy_hours_max:
        return False

    if cond.event_summary_matches is not None:
        pattern = re.compile(cond.event_summary_matches, re.IGNORECASE)
        if not any(pattern.search(ev.summary or "") for ev in events):
            return False
    return True


def _to_result(rule: DayTypeRule | DayTypeDefault) -> DayTypeResult:
    return DayTypeResult(
        name=rule.name,
        energy=rule.energy,
        allowed_max_task_duration_min=rule.allowed_max_task_duration_min,
    )


def classify_day(
    target_date: date,
    events: list[CalendarEvent],
    busy_hours: float,
    rules: list[DayTypeRule],
    default: DayTypeDefault,
    overrides: dict[str, str],
) -> DayTypeResult:
    """Classify a single day. Manual override > first matching rule > default.

    `busy_hours` is the total binding hours (events + buffers) in the user's TZ.
    """
    iso = target_date.isoformat()
    if iso in overrides:
        target_name = overrides[iso]
        for r in rules:
            if r.name == target_name:
                return _to_result(r)
        if target_name == default.name:
            return _to_result(default)
        # Unknown override name: fall through to normal logic

    for rule in rules:
        if _matches(rule.if_, target_date, events, busy_hours):
            return _to_result(rule)
    return _to_result(default)
