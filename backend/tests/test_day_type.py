from datetime import UTC, date, datetime

from app.schemas.calendar import CalendarEvent
from app.schemas.settings import (
    DayTypeCondition,
    DayTypeDefault,
    DayTypeRule,
    build_default_settings,
)
from app.services.slots.day_type import classify_day


def _ev(eid: str, summary: str, h: int = 10) -> CalendarEvent:
    return CalendarEvent(
        id=eid,
        calendar_id="primary",
        summary=summary,
        description=None,
        start=datetime(2026, 5, 11, h, 0, tzinfo=UTC),
        end=datetime(2026, 5, 11, h + 1, 0, tzinfo=UTC),
        all_day=False,
        location=None,
        status="confirmed",
    )


def _settings():
    return build_default_settings()


def test_intern_day_falls_under_busy_hours_classification() -> None:
    """Intern days no longer get a special rule — they're classified by busy
    hours like any other day (8h intern → heavy_day)."""
    s = _settings()
    events = [_ev("a", "インターン勤務"), _ev("b", "授業")]
    r = classify_day(
        date(2026, 5, 11),
        events,
        8.0,
        s.day_type_rules,
        s.day_type_default,
        {},
    )
    assert r.name == "heavy_day"


def test_heavy_day_when_busy_hours_high() -> None:
    s = _settings()
    events = [_ev(str(i), f"授業{i}") for i in range(5)]
    r = classify_day(
        date(2026, 5, 11), events, 7.0, s.day_type_rules, s.day_type_default, {}
    )
    assert r.name == "heavy_day"


def test_medium_day_for_moderate_busy_hours() -> None:
    s = _settings()
    events = [_ev("a", "現代国際社会論"), _ev("b", "物性化学")]
    r = classify_day(
        date(2026, 5, 11), events, 4.0, s.day_type_rules, s.day_type_default, {}
    )
    assert r.name == "medium_day"


def test_light_day_when_busy_hours_low() -> None:
    s = _settings()
    events = [_ev("a", "短い予定")]
    r = classify_day(
        date(2026, 5, 11), events, 1.5, s.day_type_rules, s.day_type_default, {}
    )
    assert r.name == "light_day"


def test_free_day_when_no_events() -> None:
    s = _settings()
    r = classify_day(date(2026, 5, 11), [], 0.0, s.day_type_rules, s.day_type_default, {})
    assert r.name == "free_day"


def test_override_takes_precedence() -> None:
    s = _settings()
    events = [_ev(str(i), f"x{i}") for i in range(5)]
    r = classify_day(
        date(2026, 5, 11),
        events,
        7.0,
        s.day_type_rules,
        s.day_type_default,
        {"2026-05-11": "free_day"},
    )
    assert r.name == "free_day"


def test_override_with_unknown_name_falls_through() -> None:
    s = _settings()
    r = classify_day(
        date(2026, 5, 11),
        [],
        0.0,
        s.day_type_rules,
        s.day_type_default,
        {"2026-05-11": "ghost_rule"},
    )
    assert r.name == "free_day"


def test_weekday_match() -> None:
    rule = DayTypeRule(
        name="tuesday_pe",
        **{"if": DayTypeCondition(weekday="tuesday")},
        energy=0.5,
        allowed_max_task_duration_min=120,
    )
    default = DayTypeDefault(
        name="normal", energy=0.7, allowed_max_task_duration_min=180
    )
    # 2026-05-12 is a Tuesday
    r = classify_day(date(2026, 5, 12), [], 0.0, [rule], default, {})
    assert r.name == "tuesday_pe"
    # 2026-05-13 is a Wednesday
    r = classify_day(date(2026, 5, 13), [], 0.0, [rule], default, {})
    assert r.name == "normal"


def test_total_busy_hours_min_filter() -> None:
    rule = DayTypeRule(
        name="busy_morning",
        **{"if": DayTypeCondition(total_busy_hours_min=2.0)},
        energy=0.5,
        allowed_max_task_duration_min=90,
    )
    default = DayTypeDefault(
        name="normal", energy=0.7, allowed_max_task_duration_min=180
    )
    # 1 hour busy → does not match (< 2)
    r = classify_day(date(2026, 5, 12), [], 1.0, [rule], default, {})
    assert r.name == "normal"
    # 3 hours busy → matches (>= 2)
    r = classify_day(date(2026, 5, 12), [], 3.0, [rule], default, {})
    assert r.name == "busy_morning"
