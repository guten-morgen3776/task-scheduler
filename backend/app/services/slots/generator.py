from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.calendar import CalendarEvent
from app.schemas.settings import SettingsRead, WEEKDAYS
from app.services.google import calendar as calendar_service
from app.services.slots import settings as settings_service
from app.services.slots.buffer import (
    compute_busy_periods,
    compute_location_windows,
    location_at,
    split_at_window_boundaries,
    subtract_busy,
    total_busy_hours_for_day,
)
from app.services.slots.day_type import classify_day
from app.services.slots.domain import BusyPeriod, LocationWindow, Slot, make_slot_id


def _iter_dates(start_date: date, end_date: date):
    cur = start_date
    while cur <= end_date:
        yield cur
        cur += timedelta(days=1)


def _parse_hhmm(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def _events_overlapping_day(
    events: list[CalendarEvent], target_date: date, tz: ZoneInfo
) -> list[CalendarEvent]:
    day_start = datetime.combine(target_date, time(0, 0), tzinfo=tz)
    day_end = day_start + timedelta(days=1)
    day_start_utc = day_start.astimezone(UTC)
    day_end_utc = day_end.astimezone(UTC)
    return [ev for ev in events if ev.end > day_start_utc and ev.start < day_end_utc]


def _split_into_chunks(
    start: datetime, end: datetime, max_min: int, min_min: int
) -> list[tuple[datetime, int]]:
    chunks: list[tuple[datetime, int]] = []
    cursor = start
    while cursor < end:
        remaining_min = int((end - cursor).total_seconds() / 60)
        chunk_min = min(max_min, remaining_min)
        if chunk_min >= min_min:
            chunks.append((cursor, chunk_min))
        cursor = cursor + timedelta(minutes=chunk_min)
    return chunks


async def _resolve_calendar_ids(
    db: AsyncSession, user_id: str, settings: SettingsRead
) -> list[str]:
    """Decide which calendars contribute busy time for slot generation.

    Resolution order:
      1. `busy_calendar_ids` set → use exactly those.
      2. Otherwise → fetch every calendar the user has access to, minus the
         ones in `ignore_calendar_ids`. This matches the project's stated
         policy of "treat all non-holiday calendars as busy by default".
    """
    if settings.busy_calendar_ids:
        return list(settings.busy_calendar_ids)
    all_calendars = await calendar_service.list_calendars(db, user_id)
    ignore = set(settings.ignore_calendar_ids)
    return [c.id for c in all_calendars if c.id not in ignore]


def _generate_for_day(
    target_date: date,
    events: list[CalendarEvent],
    busy: list[BusyPeriod],
    windows: list[LocationWindow],
    settings: SettingsRead,
    range_start_utc: datetime,
    range_end_utc: datetime,
    tz: ZoneInfo,
    *,
    extend_work_hours_until: str | None = None,
    extended_energy_multiplier: float = 0.3,
) -> list[Slot]:
    weekday = WEEKDAYS[target_date.weekday()]
    work_day = settings.work_hours.for_weekday(weekday)
    if not work_day.slots:
        return []

    events_today = _events_overlapping_day(events, target_date, tz)
    busy_hours = total_busy_hours_for_day(target_date, busy, tz)
    day_type = classify_day(
        target_date,
        events_today,
        busy_hours,
        settings.day_type_rules,
        settings.day_type_default,
        settings.day_type_overrides,
    )

    def _emit_slots(
        ws_start: datetime,
        ws_end: datetime,
        *,
        energy: float,
    ) -> list[Slot]:
        produced: list[Slot] = []
        free_intervals = subtract_busy((ws_start, ws_end), busy)
        for fs, fe in free_intervals:
            for sub_fs, sub_fe in split_at_window_boundaries((fs, fe), windows):
                duration_total = int((sub_fe - sub_fs).total_seconds() / 60)
                if duration_total < settings.slot_min_duration_min:
                    continue
                slot_location = location_at(sub_fs, windows)
                for chunk_start, chunk_min in _split_into_chunks(
                    sub_fs,
                    sub_fe,
                    settings.slot_max_duration_min,
                    settings.slot_min_duration_min,
                ):
                    produced.append(
                        Slot(
                            id=make_slot_id(chunk_start, chunk_min),
                            start=chunk_start,
                            duration_min=chunk_min,
                            energy_score=energy,
                            allowed_max_task_duration_min=day_type.allowed_max_task_duration_min,
                            day_type=day_type.name,
                            location=slot_location,
                        )
                    )
        return produced

    out: list[Slot] = []
    for ws in work_day.slots:
        ws_start_local = datetime.combine(target_date, _parse_hhmm(ws.start), tzinfo=tz)
        ws_end_local = datetime.combine(target_date, _parse_hhmm(ws.end), tzinfo=tz)

        ws_start = max(ws_start_local.astimezone(UTC), range_start_utc)
        ws_end = min(ws_end_local.astimezone(UTC), range_end_utc)
        if ws_start >= ws_end:
            continue
        out.extend(_emit_slots(ws_start, ws_end, energy=day_type.energy))

    # Fallback slots beyond work_hours, used only when the standard pass is
    # infeasible. Their `energy_score` is scaled down so the optimizer prefers
    # normal-hour slots whenever it can.
    if extend_work_hours_until and work_day.slots:
        last_end = _parse_hhmm(work_day.slots[-1].end)
        extend_end = _parse_hhmm(extend_work_hours_until)
        if extend_end > last_end:
            ext_start_local = datetime.combine(target_date, last_end, tzinfo=tz)
            ext_end_local = datetime.combine(target_date, extend_end, tzinfo=tz)
            ext_start = max(ext_start_local.astimezone(UTC), range_start_utc)
            ext_end = min(ext_end_local.astimezone(UTC), range_end_utc)
            if ext_start < ext_end:
                out.extend(
                    _emit_slots(
                        ext_start,
                        ext_end,
                        energy=day_type.energy * extended_energy_multiplier,
                    )
                )
    return out


async def generate_slots(
    db: AsyncSession,
    user_id: str,
    start: datetime,
    end: datetime,
    *,
    min_duration_override: int | None = None,
    max_duration_override: int | None = None,
    extra_busy_periods: list[BusyPeriod] | None = None,
    extra_windows: list[LocationWindow] | None = None,
    exclude_app_marked_events: bool = False,
    extend_work_hours_until: str | None = None,
    extended_energy_multiplier: float = 0.3,
) -> list[Slot]:
    """Generate available slots for `[start, end)`.

    `extra_busy_periods` adds extra busy time (e.g., fixed task fragments).
    `extra_windows` adds extra location windows (e.g., voluntary visits).
    `exclude_app_marked_events` drops events written by this app from the busy
    set so re-optimization can re-place those tasks. Required to be `True` when
    re-optimizing after a /write.
    """
    settings = await settings_service.get_or_create_settings(db, user_id)

    if min_duration_override is not None:
        settings = settings.model_copy(update={"slot_min_duration_min": min_duration_override})
    if max_duration_override is not None:
        settings = settings.model_copy(update={"slot_max_duration_min": max_duration_override})

    calendar_ids = await _resolve_calendar_ids(db, user_id, settings)
    events = await calendar_service.list_events(
        db, user_id, start=start, end=end, calendar_ids=calendar_ids
    )
    if settings.ignore_all_day_events:
        events = [e for e in events if not e.all_day]
    if exclude_app_marked_events:
        events = [
            e
            for e in events
            if e.extended_properties_private.get("task_scheduler") != "1"
        ]

    tz = ZoneInfo(settings.work_hours.timezone)
    windows = compute_location_windows(
        events, settings.calendar_location_rules, settings.location_commutes, tz
    )
    if extra_windows:
        windows = list(windows) + list(extra_windows)
        windows.sort(key=lambda w: w.start)
    busy = compute_busy_periods(events, windows)
    if extra_busy_periods:
        busy = list(busy) + list(extra_busy_periods)
        busy.sort(key=lambda p: p.start)

    start_local = start.astimezone(tz)
    end_local = end.astimezone(tz)

    range_start_utc = start.astimezone(UTC)
    range_end_utc = end.astimezone(UTC)

    slots: list[Slot] = []
    for d in _iter_dates(start_local.date(), end_local.date()):
        slots.extend(
            _generate_for_day(
                d,
                events,
                busy,
                windows,
                settings,
                range_start_utc,
                range_end_utc,
                tz,
                extend_work_hours_until=extend_work_hours_until,
                extended_energy_multiplier=extended_energy_multiplier,
            )
        )
    slots.sort(key=lambda s: s.start)
    return slots
