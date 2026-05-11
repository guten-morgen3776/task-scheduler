from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.schemas.calendar import CalendarEvent
from app.schemas.settings import CalendarLocationRule, LocationCommute
from app.services.slots.buffer import (
    assign_event_location,
    compute_busy_periods,
    compute_location_windows,
    location_at,
    split_at_window_boundaries,
    subtract_busy,
)
from app.services.slots.domain import BusyPeriod, LocationWindow

JST = ZoneInfo("Asia/Tokyo")


def _ev(
    eid: str,
    summary: str,
    start: datetime,
    end: datetime,
    *,
    calendar_id: str = "primary",
    location: str | None = None,
) -> CalendarEvent:
    return CalendarEvent(
        id=eid,
        calendar_id=calendar_id,
        summary=summary,
        description=None,
        start=start,
        end=end,
        all_day=False,
        location=location,
        status="confirmed",
    )


def _at(h: int, m: int = 0) -> datetime:
    return datetime(2026, 5, 11, h, m, tzinfo=UTC)


def _at_jst(h: int, m: int = 0) -> datetime:
    return datetime(2026, 5, 11, h, m, tzinfo=JST)


# ──────────────────────────────────────────────────────────────────────────
# assign_event_location
# ──────────────────────────────────────────────────────────────────────────


def test_assign_by_calendar_id() -> None:
    ev = _ev("e", "授業", _at(1), _at(3), calendar_id="utas-cal")
    rules = [CalendarLocationRule(calendar_id="utas-cal", location="university")]
    assert assign_event_location(ev, rules) == "university"


def test_assign_by_summary_match() -> None:
    ev = _ev("e", "インターン勤務", _at(1), _at(3))
    rules = [
        CalendarLocationRule(event_summary_matches=r"intern|インターン", location="office")
    ]
    assert assign_event_location(ev, rules) == "office"


def test_assign_no_match_returns_none() -> None:
    ev = _ev("e", "ジム", _at(1), _at(3))
    rules = [CalendarLocationRule(calendar_id="other", location="university")]
    assert assign_event_location(ev, rules) is None


def test_assign_first_rule_wins() -> None:
    ev = _ev("e", "intern at university", _at(1), _at(3))
    rules = [
        CalendarLocationRule(event_summary_matches=r"university", location="university"),
        CalendarLocationRule(event_summary_matches=r"intern", location="office"),
    ]
    assert assign_event_location(ev, rules) == "university"


# ──────────────────────────────────────────────────────────────────────────
# compute_location_windows
# ──────────────────────────────────────────────────────────────────────────


def _utas_rule() -> CalendarLocationRule:
    return CalendarLocationRule(calendar_id="utas-cal", location="university")


def _utas_commute() -> dict[str, LocationCommute]:
    return {"university": LocationCommute(to_min=30, from_min=20)}


def test_window_groups_same_location_events_in_one_day() -> None:
    # 10:25-12:10 と 13:00-14:45 (JST) の 2 件 → 1 つの大学ウィンドウに集約
    e1 = _ev("c1", "現代国際社会論", _at_jst(10, 25), _at_jst(12, 10), calendar_id="utas-cal")
    e2 = _ev("c2", "物性化学", _at_jst(13, 0), _at_jst(14, 45), calendar_id="utas-cal")
    windows = compute_location_windows([e1, e2], [_utas_rule()], _utas_commute(), JST)
    assert len(windows) == 1
    w = windows[0]
    assert w.location == "university"
    assert w.start == _at_jst(9, 55).astimezone(UTC)  # 10:25 - 30
    assert w.end == _at_jst(15, 5).astimezone(UTC)    # 14:45 + 20


def test_window_no_match_means_no_window() -> None:
    ev = _ev("e", "ジム", _at(1), _at(3))
    windows = compute_location_windows([ev], [_utas_rule()], _utas_commute(), JST)
    assert windows == []


def test_multiple_locations_yield_separate_windows() -> None:
    e_uni = _ev("u", "授業", _at_jst(10, 25), _at_jst(12, 10), calendar_id="utas-cal")
    e_int = _ev("i", "インターン勤務", _at_jst(14, 0), _at_jst(18, 0))
    rules = [
        _utas_rule(),
        CalendarLocationRule(event_summary_matches=r"インターン", location="office"),
    ]
    commutes = {
        "university": LocationCommute(to_min=30, from_min=30),
        "office": LocationCommute(to_min=20, from_min=20),
    }
    windows = compute_location_windows([e_uni, e_int], rules, commutes, JST)
    assert len(windows) == 2
    locs = {w.location for w in windows}
    assert locs == {"university", "office"}


# ──────────────────────────────────────────────────────────────────────────
# compute_busy_periods (the bug-fix test)
# ──────────────────────────────────────────────────────────────────────────


def test_inner_gap_between_same_location_events_is_free() -> None:
    """Two university events at 10:25-12:10 and 13:00-14:45.

    Old `location_buffers` model would mark the entire 10:25-14:45 (and even
    the surrounding 30/20 buffers) as busy. The new window model leaves the
    12:10-13:00 gap FREE so the user can do tasks at the library/lounge.
    """
    e1 = _ev("c1", "授業1", _at_jst(10, 25), _at_jst(12, 10), calendar_id="utas-cal")
    e2 = _ev("c2", "授業2", _at_jst(13, 0), _at_jst(14, 45), calendar_id="utas-cal")
    windows = compute_location_windows([e1, e2], [_utas_rule()], _utas_commute(), JST)
    busy = compute_busy_periods([e1, e2], windows)

    # The 12:10-13:00 gap should NOT overlap any busy period.
    gap_start = _at_jst(12, 10).astimezone(UTC)
    gap_end = _at_jst(13, 0).astimezone(UTC)
    for bp in busy:
        # No busy period should start strictly inside the gap
        assert not (gap_start < bp.start < gap_end)
        # No busy period should fully contain or cover the gap mid-point
        midpoint = _at_jst(12, 30).astimezone(UTC)
        assert not (bp.start <= midpoint < bp.end)


def test_window_edges_are_busy_commute() -> None:
    """The 30 min before the first event and the 20 min after the last
    are busy (commute), even though no event itself covers them."""
    e = _ev("c", "授業", _at_jst(10, 25), _at_jst(12, 10), calendar_id="utas-cal")
    windows = compute_location_windows([e], [_utas_rule()], _utas_commute(), JST)
    busy = compute_busy_periods([e], windows)
    # commute_to: 09:55 -> 10:25
    commute_to_start = _at_jst(9, 55).astimezone(UTC)
    busy_at_commute_to = any(
        bp.start <= commute_to_start < bp.end for bp in busy
    )
    assert busy_at_commute_to


def test_linger_after_class_keeps_window_open() -> None:
    """With linger_after_min, the time after the last class is FREE at the
    location (e.g., staying at the library) until the actual commute home."""
    # Class 14:55-16:40 with linger 120 min and commute_from 30 min
    # → window: 14:25 → 16:40 + 120 + 30 = 19:10
    # Linger zone (free at university): 16:40 → 18:40
    # Commute home (busy): 18:40 → 19:10
    e = _ev("c", "授業", _at_jst(14, 55), _at_jst(16, 40), calendar_id="utas-cal")
    rules = [_utas_rule()]
    commutes = {
        "university": LocationCommute(to_min=30, from_min=30, linger_after_min=120)
    }
    windows = compute_location_windows([e], rules, commutes, JST)
    assert len(windows) == 1
    w = windows[0]
    assert w.end == _at_jst(19, 10).astimezone(UTC)
    assert w.commute_from_min == 30

    busy = compute_busy_periods([e], windows)
    # 17:30 should NOT be busy (linger zone, free at university)
    midpoint = _at_jst(17, 30).astimezone(UTC)
    assert all(not (bp.start <= midpoint < bp.end) for bp in busy)
    # 18:50 SHOULD be busy (inside the commute_from at the end)
    in_commute = _at_jst(18, 50).astimezone(UTC)
    assert any(bp.start <= in_commute < bp.end for bp in busy)


def test_default_no_linger_for_office() -> None:
    """LocationCommute defaults to linger_after_min=0 → window ends at last_event + from_min."""
    e = _ev("i", "intern", _at_jst(10, 0), _at_jst(18, 0))
    rules = [
        CalendarLocationRule(event_summary_matches=r"intern", location="office")
    ]
    commutes = {"office": LocationCommute(to_min=20, from_min=20)}
    windows = compute_location_windows([e], rules, commutes, JST)
    w = windows[0]
    assert w.end == _at_jst(18, 20).astimezone(UTC)
    assert w.commute_from_min == 20


def test_event_without_location_still_busy() -> None:
    ev = _ev("e", "ジム", _at(1), _at(3))  # no rule matches
    busy = compute_busy_periods([ev], [])
    assert any(bp.start == _at(1) and bp.end == _at(3) for bp in busy)


# ──────────────────────────────────────────────────────────────────────────
# subtract_busy
# ──────────────────────────────────────────────────────────────────────────


def test_subtract_busy_no_overlap() -> None:
    out = subtract_busy(
        (_at(9), _at(22)),
        [BusyPeriod(start=_at(10), end=_at(11), sources=("x",))],
    )
    assert out == [(_at(9), _at(10)), (_at(11), _at(22))]


def test_subtract_busy_full_cover() -> None:
    out = subtract_busy(
        (_at(9), _at(22)),
        [BusyPeriod(start=_at(8), end=_at(23), sources=("x",))],
    )
    assert out == []


def test_subtract_busy_edge_touch_does_not_split() -> None:
    out = subtract_busy(
        (_at(9), _at(22)),
        [BusyPeriod(start=_at(22), end=_at(23), sources=("x",))],
    )
    assert out == [(_at(9), _at(22))]


# ──────────────────────────────────────────────────────────────────────────
# split_at_window_boundaries / location_at
# ──────────────────────────────────────────────────────────────────────────


def test_split_at_window_boundaries_cuts_at_start_and_end() -> None:
    interval = (_at(8), _at(20))
    w = LocationWindow(location="university", start=_at(10), end=_at(15))
    out = split_at_window_boundaries(interval, [w])
    assert out == [(_at(8), _at(10)), (_at(10), _at(15)), (_at(15), _at(20))]


def test_split_no_overlap_returns_unchanged() -> None:
    interval = (_at(8), _at(9))
    w = LocationWindow(location="university", start=_at(10), end=_at(15))
    out = split_at_window_boundaries(interval, [w])
    assert out == [(_at(8), _at(9))]


def test_location_at_inside_window() -> None:
    w = LocationWindow(location="university", start=_at(10), end=_at(15))
    assert location_at(_at(12), [w]) == "university"


def test_location_at_outside_returns_home() -> None:
    w = LocationWindow(location="university", start=_at(10), end=_at(15))
    assert location_at(_at(8), [w]) == "home"
    assert location_at(_at(15), [w]) == "home"  # right edge is exclusive


def test_voluntary_window_busy_periods():
    """is_voluntary=True window: commute_to at start, commute_from at end, middle free."""
    from datetime import UTC, datetime
    from app.services.slots.buffer import compute_busy_periods
    from app.services.slots.domain import LocationWindow

    w = LocationWindow(
        location="university",
        start=datetime(2026, 5, 12, 0, 0, tzinfo=UTC),    # 09:00 JST - 30min
        end=datetime(2026, 5, 12, 10, 30, tzinfo=UTC),    # 19:00 JST + 30min
        commute_from_min=30,
        commute_to_min=30,
        is_voluntary=True,
    )
    busy = compute_busy_periods(events=[], windows=[w])
    # Expect: [00:00–00:30 commute_to, 10:00–10:30 commute_from]
    assert len(busy) == 2
    assert busy[0].start == datetime(2026, 5, 12, 0, 0, tzinfo=UTC)
    assert busy[0].end == datetime(2026, 5, 12, 0, 30, tzinfo=UTC)
    assert busy[1].start == datetime(2026, 5, 12, 10, 0, tzinfo=UTC)
    assert busy[1].end == datetime(2026, 5, 12, 10, 30, tzinfo=UTC)


def test_assign_location_skips_rule_when_unless_day_has_calendar_matches():
    """A rule with `unless_day_has_calendar_ids` is bypassed when any same-day
    event's calendar_id is in that list. Used for: intern→office, BUT when UTAS
    has a class the same day, intern is remote → fallback rule → university."""
    from datetime import UTC, datetime
    from app.schemas.calendar import CalendarEvent
    from app.schemas.settings import CalendarLocationRule
    from app.services.slots.buffer import assign_event_location

    def _ev(eid, calendar_id, summary, hour) -> CalendarEvent:
        return CalendarEvent(
            id=eid,
            calendar_id=calendar_id,
            summary=summary,
            description=None,
            start=datetime(2026, 5, 12, hour, 0, tzinfo=UTC),
            end=datetime(2026, 5, 12, hour + 1, 0, tzinfo=UTC),
            all_day=False,
            location=None,
            status="confirmed",
        )

    UTAS = "utas@import.calendar.google.com"
    rules = [
        CalendarLocationRule(calendar_id=UTAS, location="university"),
        CalendarLocationRule(
            event_summary_matches=r"intern|インターン",
            location="office",
            unless_day_has_calendar_ids=[UTAS],
        ),
        CalendarLocationRule(
            event_summary_matches=r"intern|インターン",
            location="university",
        ),
    ]

    intern = _ev("intern1", "primary", "インターン勤務", 9)
    utas_event = _ev("utas1", UTAS, "物性化学", 14)

    # Day with intern only → office.
    assert assign_event_location(intern, rules, same_day_events=[intern]) == "office"

    # Day with both intern and a UTAS class → first rule is bypassed → uni.
    assert (
        assign_event_location(intern, rules, same_day_events=[intern, utas_event])
        == "university"
    )

    # UTAS event itself is always university (matches first rule).
    assert (
        assign_event_location(utas_event, rules, same_day_events=[intern, utas_event])
        == "university"
    )
