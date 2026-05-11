from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest_asyncio
from httpx import AsyncClient

from app.schemas.calendar import CalendarEvent
from app.services.google import calendar as calendar_service
from app.services.slots import settings as settings_service

JST = ZoneInfo("Asia/Tokyo")


def _ev(eid: str, summary: str, start_jst: datetime, end_jst: datetime) -> CalendarEvent:
    return CalendarEvent(
        id=eid,
        calendar_id="primary",
        summary=summary,
        description=None,
        start=start_jst.astimezone(UTC),
        end=end_jst.astimezone(UTC),
        all_day=False,
        location=None,
        status="confirmed",
    )


def _jst(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=JST)


@pytest_asyncio.fixture
async def fake_calendar(monkeypatch):
    """Replace calendar_service.list_events with an injectable fake."""

    state: dict = {"events": []}

    async def fake_list_events(db, user_id, *, start, end, calendar_ids):
        return [
            ev
            for ev in state["events"]
            if ev.end > start.astimezone(UTC) and ev.start < end.astimezone(UTC)
        ]

    async def fake_list_calendars(db, user_id):
        return []

    monkeypatch.setattr(calendar_service, "list_events", fake_list_events)
    monkeypatch.setattr(calendar_service, "list_calendars", fake_list_calendars)
    return state


async def _query(client: AsyncClient, start_jst: datetime, end_jst: datetime) -> list[dict]:
    r = await client.get(
        "/calendar/slots",
        params={"start": start_jst.isoformat(), "end": end_jst.isoformat()},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_empty_calendar_returns_full_work_hours(
    client: AsyncClient, fake_calendar
) -> None:
    # Monday 2026-05-11, no events; default work hours 09:00-12:00 + 13:00-19:00 (9h)
    slots = await _query(client, _jst(2026, 5, 11, 0), _jst(2026, 5, 12, 0))
    # Morning block (3h): 1×120min + 1×60min = 2 slots
    # Afternoon block (6h): 3×120min = 3 slots → 5 total
    assert len(slots) == 5
    assert all(s["day_type"] == "free_day" for s in slots)
    assert sum(s["duration_min"] for s in slots) == 9 * 60
    # Earliest slot starts at 09:00 JST = 00:00 UTC
    assert slots[0]["start"].endswith("T00:00:00Z")
    # No slot starts at lunch hour (12:00 JST = 03:00 UTC)
    for s in slots:
        assert "T03:00:00Z" not in s["start"]


async def test_intern_day_classified_by_busy_hours(client: AsyncClient, fake_calendar) -> None:
    """8 hours of intern work + commute = >= 6h busy → heavy_day. There's no
    longer an intern-specific classification."""
    fake_calendar["events"] = [
        _ev("i1", "インターン勤務", _jst(2026, 5, 11, 10), _jst(2026, 5, 11, 18))
    ]
    slots = await _query(client, _jst(2026, 5, 11, 0), _jst(2026, 5, 12, 0))
    assert all(s["day_type"] == "heavy_day" for s in slots)
    # Buffer 20/20 → busy 09:40 - 18:20 → only 09:00-09:40 (40min) before is
    # available inside the configured 09:00-12:00 + 13:00-19:00 work hours.
    pre = [s for s in slots if s["start"] == _jst(2026, 5, 11, 9).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")]
    assert len(pre) == 1
    assert pre[0]["duration_min"] == 40
    busy_window_start = _jst(2026, 5, 11, 10).astimezone(UTC)
    busy_window_end = _jst(2026, 5, 11, 18).astimezone(UTC)
    for s in slots:
        s_start = datetime.fromisoformat(s["start"])
        assert not (busy_window_start <= s_start < busy_window_end)


async def test_heavy_day_has_few_slots(client: AsyncClient, fake_calendar) -> None:
    # 5 university classes back-to-back through the day → ~9 hours busy
    fake_calendar["events"] = [
        _ev("c1", "現代国際社会論", _jst(2026, 5, 11, 8, 30), _jst(2026, 5, 11, 10, 15)),
        _ev("c2", "物性化学", _jst(2026, 5, 11, 10, 25), _jst(2026, 5, 11, 12, 10)),
        _ev("c3", "宇宙科学実習Ⅰ", _jst(2026, 5, 11, 13, 0), _jst(2026, 5, 11, 14, 45)),
        _ev("c4", "数学演習", _jst(2026, 5, 11, 14, 55), _jst(2026, 5, 11, 16, 40)),
        _ev("c5", "情報リテラシー", _jst(2026, 5, 11, 16, 50), _jst(2026, 5, 11, 18, 35)),
    ]
    slots = await _query(client, _jst(2026, 5, 11, 0), _jst(2026, 5, 12, 0))
    assert all(s["day_type"] == "heavy_day" for s in slots)
    # Work hours end 19:00, last class 18:35 → only 25 min after, less than min_slot
    # Mainly small gaps remain
    assert len(slots) <= 3


async def test_short_intervals_below_min_are_dropped(
    client: AsyncClient, fake_calendar
) -> None:
    # Almost-fill the day; leave only 20 min (below 30 min default min) at the end
    fake_calendar["events"] = [
        _ev("a", "授業", _jst(2026, 5, 11, 9, 0), _jst(2026, 5, 11, 21, 40)),
    ]
    slots = await _query(client, _jst(2026, 5, 11, 0), _jst(2026, 5, 12, 0))
    # Remaining 21:40-22:00 = 20 min < 30 min min → dropped
    assert slots == []


async def test_long_free_window_split_by_max(
    client: AsyncClient, fake_calendar
) -> None:
    # No events; 9-12 + 13-19 = 9h with lunch break.
    fake_calendar["events"] = []
    slots = await _query(client, _jst(2026, 5, 11, 0), _jst(2026, 5, 12, 0))
    durations = [s["duration_min"] for s in slots]
    assert all(d <= 120 for d in durations)
    assert sum(durations) == 9 * 60
    # No slot starts at lunch (12:00 JST = 03:00 UTC)
    for s in slots:
        assert "T03:00:00Z" not in s["start"]


async def test_override_query_overrides(client: AsyncClient, fake_calendar) -> None:
    fake_calendar["events"] = []
    r = await client.get(
        "/calendar/slots",
        params={
            "start": _jst(2026, 5, 11, 0).isoformat(),
            "end": _jst(2026, 5, 12, 0).isoformat(),
            "max_duration_min": 60,
        },
    )
    assert r.status_code == 200
    durations = [s["duration_min"] for s in r.json()]
    assert all(d <= 60 for d in durations)


async def test_day_type_override_applied(client: AsyncClient, fake_calendar) -> None:
    await client.put(
        "/settings", json={"day_type_overrides": {"2026-05-11": "free_day"}}
    )
    fake_calendar["events"] = [
        _ev(str(i), f"授業{i}", _jst(2026, 5, 11, 9 + i, 0), _jst(2026, 5, 11, 9 + i, 30))
        for i in range(5)
    ]
    slots = await _query(client, _jst(2026, 5, 11, 0), _jst(2026, 5, 12, 0))
    # Without override would be uni_heavy, but override forces free_day
    assert all(s["day_type"] == "free_day" for s in slots)


def _all_day(eid: str, summary: str, day_jst: datetime) -> CalendarEvent:
    start = day_jst.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    end = (day_jst.replace(hour=23, minute=59, second=59, microsecond=999999)).astimezone(UTC)
    return CalendarEvent(
        id=eid,
        calendar_id="primary",
        summary=summary,
        description=None,
        start=start,
        end=end,
        all_day=True,
        location=None,
        status="confirmed",
    )


async def test_all_day_event_ignored_by_default(client: AsyncClient, fake_calendar) -> None:
    fake_calendar["events"] = [_all_day("rem", "白衣ゴーグル", _jst(2026, 5, 11, 0))]
    slots = await _query(client, _jst(2026, 5, 11, 0), _jst(2026, 5, 12, 0))
    # All-day reminder should be ignored: full day classified as free_day, slots generated
    assert len(slots) > 0
    assert all(s["day_type"] == "free_day" for s in slots)


async def test_all_day_event_respected_when_flag_off(
    client: AsyncClient, fake_calendar
) -> None:
    await client.put("/settings", json={"ignore_all_day_events": False})
    fake_calendar["events"] = [_all_day("rem", "白衣ゴーグル", _jst(2026, 5, 11, 0))]
    slots = await _query(client, _jst(2026, 5, 11, 0), _jst(2026, 5, 12, 0))
    # All-day reminder now blocks the entire work window
    assert slots == []


async def test_resolve_calendar_ids_defaults_to_all_calendars(
    db_session, test_user, monkeypatch
) -> None:
    """When busy_calendar_ids is empty, all accessible calendars become busy
    sources by default (matches the project's stated policy). Regression test
    for the bug where empty busy + empty ignore returned just ['primary']."""
    from app.schemas.calendar import CalendarInfo
    from app.services.slots.generator import _resolve_calendar_ids

    async def fake_list_calendars(db, user_id):
        return [
            CalendarInfo(
                id="primary",
                summary="me",
                description=None,
                primary=True,
                access_role="owner",
                background_color=None,
                selected=True,
                time_zone="Asia/Tokyo",
            ),
            CalendarInfo(
                id="utas@import.calendar.google.com",
                summary="UTAS",
                description=None,
                primary=False,
                access_role="reader",
                background_color=None,
                selected=True,
                time_zone="UTC",
            ),
            CalendarInfo(
                id="ja.japanese#holiday@group.v.calendar.google.com",
                summary="JP Holidays",
                description=None,
                primary=False,
                access_role="reader",
                background_color=None,
                selected=True,
                time_zone="Asia/Tokyo",
            ),
        ]

    monkeypatch.setattr(calendar_service, "list_calendars", fake_list_calendars)

    settings = await settings_service.get_or_create_settings(db_session, test_user.id)
    # Default: both lists empty → expect ALL calendars returned.
    result = await _resolve_calendar_ids(db_session, test_user.id, settings)
    assert set(result) == {
        "primary",
        "utas@import.calendar.google.com",
        "ja.japanese#holiday@group.v.calendar.google.com",
    }

    # With ignore set, those are excluded.
    with_ignore = settings.model_copy(
        update={
            "ignore_calendar_ids": ["ja.japanese#holiday@group.v.calendar.google.com"]
        }
    )
    result = await _resolve_calendar_ids(db_session, test_user.id, with_ignore)
    assert set(result) == {"primary", "utas@import.calendar.google.com"}

    # busy_calendar_ids takes precedence — ignore is irrelevant when set.
    with_busy = settings.model_copy(
        update={
            "busy_calendar_ids": ["primary"],
            "ignore_calendar_ids": ["something"],
        }
    )
    result = await _resolve_calendar_ids(db_session, test_user.id, with_busy)
    assert result == ["primary"]


async def test_extend_work_hours_adds_evening_slots_with_reduced_energy(
    db_session, test_user, fake_calendar
) -> None:
    """`extend_work_hours_until` appends evening slots beyond the configured
    work_hours.end, tagged with reduced energy so the optimizer only uses them
    as a fallback."""
    from app.services.slots.generator import generate_slots

    slots = await generate_slots(
        db_session,
        test_user.id,
        start=_jst(2026, 5, 11, 0),
        end=_jst(2026, 5, 12, 0),
        extend_work_hours_until="23:00",
        extended_energy_multiplier=0.3,
    )

    # 19:00 JST = 10:00 UTC marks the boundary between normal and extended.
    boundary = datetime(2026, 5, 11, 10, 0, tzinfo=UTC)
    normal = [s for s in slots if s.start < boundary]
    extended = [s for s in slots if s.start >= boundary]
    assert normal and extended
    assert all(s.energy_score == 1.0 for s in normal)
    assert all(abs(s.energy_score - 0.3) < 1e-9 for s in extended)


async def test_no_extension_means_no_evening_slots(
    db_session, test_user, fake_calendar
) -> None:
    from app.services.slots.generator import generate_slots

    slots = await generate_slots(
        db_session,
        test_user.id,
        start=_jst(2026, 5, 11, 0),
        end=_jst(2026, 5, 12, 0),
    )
    # 19:00 JST = 10:00 UTC. No slot should start at or after that.
    assert all(s.start < datetime(2026, 5, 11, 10, 0, tzinfo=UTC) for s in slots)
