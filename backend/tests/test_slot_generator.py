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


async def test_intern_day_only_after_work(client: AsyncClient, fake_calendar) -> None:
    fake_calendar["events"] = [
        _ev("i1", "インターン勤務", _jst(2026, 5, 11, 10), _jst(2026, 5, 11, 18))
    ]
    slots = await _query(client, _jst(2026, 5, 11, 0), _jst(2026, 5, 12, 0))
    # All slots should be intern_day classification
    assert all(s["day_type"] == "intern_day" for s in slots)
    # Buffer is 20/20 → busy 09:40 - 18:20 → only 09:00-09:40 (40min) before
    # and 18:20-22:00 (3h40m) after are free
    # Pre slot: 09:00-09:40 = 40 min (>= min 30, <= max 120) → 1 slot
    starts = [s["start"] for s in slots]
    # Pre-work slot exists
    pre = [s for s in slots if s["start"] == _jst(2026, 5, 11, 9).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")]
    assert len(pre) == 1
    assert pre[0]["duration_min"] == 40
    # No slot during 10:00-18:00 (busy)
    busy_window_start = _jst(2026, 5, 11, 10).astimezone(UTC)
    busy_window_end = _jst(2026, 5, 11, 18).astimezone(UTC)
    for s in slots:
        s_start = datetime.fromisoformat(s["start"])
        # No slot strictly inside the busy window (with buffer)
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
