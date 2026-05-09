"""Location-window model for busy-period computation.

For each day:
1. Each event gets a location tag via calendar_location_rules (or None).
2. Events sharing a location are collapsed into one LocationWindow whose
   boundaries include commute_to / commute_from for that location.
3. Busy periods = (events themselves) + (commute portions at window edges).
   Inner gaps between same-location events are NOT busy — the user is
   already there and can do tasks (e.g., between two university classes,
   the user is at the library).
4. Events that don't match any location rule are still busy at their own
   start/end (no commute, no window).
"""

import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.schemas.calendar import CalendarEvent
from app.schemas.settings import (
    CalendarLocationRule,
    Location,
    LocationCommute,
)
from app.services.slots.domain import BusyPeriod, LocationWindow


def assign_event_location(
    event: CalendarEvent, rules: list[CalendarLocationRule]
) -> Location | None:
    """Return the location of an event by first-match, or None if no rule matches."""
    for rule in rules:
        if rule.calendar_id is not None and event.calendar_id == rule.calendar_id:
            return rule.location
        if rule.event_summary_matches is not None:
            haystack = f"{event.summary or ''} {event.location or ''}"
            if re.search(rule.event_summary_matches, haystack, re.IGNORECASE):
                return rule.location
    return None


def _events_by_local_date(
    events: list[CalendarEvent], tz: ZoneInfo
) -> dict[date, list[CalendarEvent]]:
    by_day: dict[date, list[CalendarEvent]] = defaultdict(list)
    for ev in events:
        local_date = ev.start.astimezone(tz).date()
        by_day[local_date].append(ev)
    return by_day


def compute_location_windows(
    events: list[CalendarEvent],
    rules: list[CalendarLocationRule],
    commutes: dict[Location, LocationCommute],
    tz: ZoneInfo,
) -> list[LocationWindow]:
    """Group same-location events on the same day into windows with commute padding."""
    windows: list[LocationWindow] = []
    by_day = _events_by_local_date(events, tz)
    for _date, day_events in by_day.items():
        per_location: dict[Location, list[CalendarEvent]] = defaultdict(list)
        for ev in day_events:
            loc = assign_event_location(ev, rules)
            if loc is None or loc == "anywhere":
                continue
            per_location[loc].append(ev)

        for loc, evs in per_location.items():
            first_start = min(e.start for e in evs)
            last_end = max(e.end for e in evs)
            commute = commutes.get(loc)
            to_min = commute.to_min if commute else 0
            from_min = commute.from_min if commute else 0
            linger_after_min = commute.linger_after_min if commute else 0
            windows.append(
                LocationWindow(
                    location=loc,
                    start=first_start - timedelta(minutes=to_min),
                    # Window extends past last event by linger + commute back.
                    # The linger zone is FREE at location; the trailing
                    # `commute_from_min` minutes are the actual return commute.
                    end=last_end + timedelta(minutes=linger_after_min + from_min),
                    commute_from_min=from_min,
                )
            )
    windows.sort(key=lambda w: w.start)
    return windows


def compute_busy_periods(
    events: list[CalendarEvent], windows: list[LocationWindow]
) -> list[BusyPeriod]:
    """busy = each event itself + the commute portions at the edges of each window.

    Inner gaps between same-location events stay free.
    """
    periods: list[BusyPeriod] = [
        BusyPeriod(start=ev.start, end=ev.end, sources=(ev.id,)) for ev in events
    ]

    # For each window, the commute_to portion is window.start ~ first_event.start (busy).
    # The commute_from portion is the LAST `commute_from_min` minutes of the window
    # (busy). Anything between last_event.end and the start of commute_from is the
    # linger zone (free at location).
    for w in windows:
        events_in = [ev for ev in events if w.start <= ev.start and ev.end <= w.end]
        if not events_in:
            periods.append(
                BusyPeriod(start=w.start, end=w.end, sources=(f"window:{w.location}",))
            )
            continue
        first_ev = min(events_in, key=lambda e: e.start)
        if w.start < first_ev.start:
            periods.append(
                BusyPeriod(
                    start=w.start,
                    end=first_ev.start,
                    sources=(f"commute_to:{w.location}",),
                )
            )
        if w.commute_from_min > 0:
            commute_from_start = w.end - timedelta(minutes=w.commute_from_min)
            periods.append(
                BusyPeriod(
                    start=commute_from_start,
                    end=w.end,
                    sources=(f"commute_from:{w.location}",),
                )
            )

    return _merge_overlapping(periods)


def _merge_overlapping(periods: list[BusyPeriod]) -> list[BusyPeriod]:
    if not periods:
        return []
    sorted_periods = sorted(periods, key=lambda p: p.start)
    merged: list[BusyPeriod] = [sorted_periods[0]]
    for p in sorted_periods[1:]:
        last = merged[-1]
        if p.start <= last.end:
            merged[-1] = BusyPeriod(
                start=last.start,
                end=max(last.end, p.end),
                sources=last.sources + p.sources,
            )
        else:
            merged.append(p)
    return merged


def subtract_busy(
    window: tuple[datetime, datetime], busy_periods: list[BusyPeriod]
) -> list[tuple[datetime, datetime]]:
    """Return free intervals within `window` that don't overlap any busy period."""
    free: list[tuple[datetime, datetime]] = [window]
    for bp in busy_periods:
        new_free: list[tuple[datetime, datetime]] = []
        for fs, fe in free:
            if bp.end <= fs or bp.start >= fe:
                new_free.append((fs, fe))
                continue
            if bp.start > fs:
                new_free.append((fs, bp.start))
            if bp.end < fe:
                new_free.append((bp.end, fe))
        free = new_free
    return free


def split_at_window_boundaries(
    interval: tuple[datetime, datetime], windows: list[LocationWindow]
) -> list[tuple[datetime, datetime]]:
    """Split a free interval so no chunk crosses a location-window boundary.

    This guarantees a single Slot has a single location.
    """
    cuts = {interval[0], interval[1]}
    for w in windows:
        if interval[0] < w.start < interval[1]:
            cuts.add(w.start)
        if interval[0] < w.end < interval[1]:
            cuts.add(w.end)
    sorted_cuts = sorted(cuts)
    return [(sorted_cuts[i], sorted_cuts[i + 1]) for i in range(len(sorted_cuts) - 1)]


def location_at(point: datetime, windows: list[LocationWindow]) -> Location:
    """Return the location at `point`, defaulting to 'home' if outside all windows."""
    for w in windows:
        if w.start <= point < w.end:
            return w.location
    return "home"


def total_busy_hours_for_day(
    target_date: date, busy: list[BusyPeriod], tz: ZoneInfo
) -> float:
    """Sum of (busy ∩ [day_start, day_end]) in user TZ, in hours."""
    day_start = datetime.combine(target_date, time(0, 0), tzinfo=tz)
    day_end = day_start + timedelta(days=1)
    total_seconds = 0.0
    for p in busy:
        s = max(p.start, day_start.astimezone(p.start.tzinfo))
        e = min(p.end, day_end.astimezone(p.end.tzinfo))
        if e > s:
            total_seconds += (e - s).total_seconds()
    return total_seconds / 3600.0
