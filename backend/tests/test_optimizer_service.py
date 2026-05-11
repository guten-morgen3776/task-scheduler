"""Unit tests for the optimizer service helpers (no DB / Google API)."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.models import Task
from app.schemas.settings import build_default_settings
from app.services.optimizer.domain import OptimizerTask
from app.services.optimizer.service import (
    _build_fixed_assignments,
    _decide_voluntary_windows,
    _fragments_to_busy,
    _is_fixed,
)
from app.services.slots.domain import Slot


def _make_task(**kwargs) -> Task:
    """Build an unsaved Task instance for tests."""
    base = dict(
        user_id="u",
        list_id="l",
        title="t",
        position="000010",
        duration_min=60,
        priority=3,
        completed=False,
        scheduled_fixed=False,
    )
    base.update(kwargs)
    return Task(**base)


def test_is_fixed_requires_both_flag_and_fragments():
    t1 = _make_task(scheduled_fixed=True, scheduled_fragments=None)
    t2 = _make_task(scheduled_fixed=False, scheduled_fragments=[{"start": "2026-05-10T03:00:00+00:00", "end": "2026-05-10T04:00:00+00:00"}])
    t3 = _make_task(scheduled_fixed=True, scheduled_fragments=[{"start": "2026-05-10T03:00:00+00:00", "end": "2026-05-10T04:00:00+00:00"}])
    assert _is_fixed(t1) is False
    assert _is_fixed(t2) is False
    assert _is_fixed(t3) is True


def test_fragments_to_busy_preserves_each_fragment():
    t = _make_task(
        scheduled_fixed=True,
        scheduled_fragments=[
            {"start": "2026-05-10T03:00:00+00:00", "end": "2026-05-10T04:00:00+00:00"},
            {"start": "2026-05-10T08:00:00+00:00", "end": "2026-05-10T09:30:00+00:00"},
        ],
    )
    busy = _fragments_to_busy([t])
    assert len(busy) == 2
    assert busy[0].start == datetime(2026, 5, 10, 3, 0, tzinfo=UTC)
    assert busy[1].end == datetime(2026, 5, 10, 9, 30, tzinfo=UTC)
    assert "fixed:" in busy[0].sources[0]


def test_build_fixed_assignments_preserves_fragments():
    t = _make_task(
        id="abc",
        scheduled_fixed=True,
        scheduled_fragments=[
            {"start": "2026-05-10T08:00:00+00:00", "end": "2026-05-10T09:30:00+00:00"},
            {"start": "2026-05-10T03:00:00+00:00", "end": "2026-05-10T04:00:00+00:00"},
        ],
    )
    [assignment] = _build_fixed_assignments([t])
    assert assignment.task_id == "abc"
    assert len(assignment.fragments) == 2
    # Fragments are sorted by start time.
    assert assignment.fragments[0].start == datetime(2026, 5, 10, 3, 0, tzinfo=UTC)
    assert assignment.fragments[0].duration_min == 60
    assert assignment.fragments[1].start == datetime(2026, 5, 10, 8, 0, tzinfo=UTC)
    assert assignment.fragments[1].duration_min == 90
    assert assignment.total_assigned_min == 150


def _slot(start: datetime, duration: int, location: str = "home") -> Slot:
    return Slot(
        id=f"slot-{start.isoformat()}-{duration}",
        start=start,
        duration_min=duration,
        energy_score=0.5,
        allowed_max_task_duration_min=240,
        day_type="normal",
        location=location,
    )


def test_decide_voluntary_windows_returns_empty_when_setting_off():
    settings = build_default_settings()
    settings = settings.model_copy(update={"voluntary_visit_locations": []})
    flexible = [OptimizerTask(id="a", title="t", duration_min=60, deadline=None, priority=3, location="university")]
    out = _decide_voluntary_windows(
        flexible_tasks=flexible,
        initial_slots=[],
        settings=settings,
        start=datetime(2026, 5, 11, 0, 0, tzinfo=UTC),
        end=datetime(2026, 5, 14, 23, 59, tzinfo=UTC),
    )
    assert out == []


def test_decide_voluntary_windows_returns_empty_when_demand_met():
    settings = build_default_settings()
    settings = settings.model_copy(update={"voluntary_visit_locations": ["university"]})
    flexible = [OptimizerTask(id="a", title="t", duration_min=60, deadline=None, priority=3, location="university")]
    tz = ZoneInfo("Asia/Tokyo")
    # 1h uni slot exists already → no need for voluntary visit.
    uni_slot = _slot(datetime(2026, 5, 11, 1, 0, tzinfo=UTC), 60, location="university")
    out = _decide_voluntary_windows(
        flexible_tasks=flexible,
        initial_slots=[uni_slot],
        settings=settings,
        start=datetime(2026, 5, 11, 0, 0, tzinfo=UTC),
        end=datetime(2026, 5, 14, 23, 59, tzinfo=UTC),
    )
    assert out == []
    assert tz  # silence unused warning


def test_decide_voluntary_windows_picks_free_days_when_demand_exceeds():
    settings = build_default_settings()
    settings = settings.model_copy(update={"voluntary_visit_locations": ["university"]})
    # 2h uni task but 0 uni minutes in slots → expect at least one voluntary window.
    flexible = [OptimizerTask(id="a", title="t", duration_min=120, deadline=None, priority=3, location="university")]
    # Free day = no slot with non-home location. Provide only home slots.
    home_slot = _slot(datetime(2026, 5, 11, 1, 0, tzinfo=UTC), 60, location="home")
    out = _decide_voluntary_windows(
        flexible_tasks=flexible,
        initial_slots=[home_slot],
        settings=settings,
        start=datetime(2026, 5, 11, 0, 0, tzinfo=UTC),
        end=datetime(2026, 5, 14, 23, 59, tzinfo=UTC),
    )
    assert len(out) >= 1
    for w in out:
        assert w.location == "university"
        assert w.is_voluntary is True
        # commute_to_min and commute_from_min should match settings.
        assert w.commute_to_min == 30
        assert w.commute_from_min == 30


def test_decide_voluntary_windows_skips_busy_location_days():
    settings = build_default_settings()
    settings = settings.model_copy(update={"voluntary_visit_locations": ["university"]})
    # A day already has uni slots (existing window) — should NOT be picked again.
    flexible = [OptimizerTask(id="a", title="t", duration_min=360, deadline=None, priority=3, location="university")]
    # 5/11 has uni slots (counts as busy), 5/12 has only home slots → 5/12 picked.
    s11 = _slot(datetime(2026, 5, 11, 1, 0, tzinfo=UTC), 60, location="university")
    s12 = _slot(datetime(2026, 5, 12, 1, 0, tzinfo=UTC), 60, location="home")
    out = _decide_voluntary_windows(
        flexible_tasks=flexible,
        initial_slots=[s11, s12],
        settings=settings,
        start=datetime(2026, 5, 11, 0, 0, tzinfo=UTC),
        end=datetime(2026, 5, 12, 23, 59, tzinfo=UTC),
    )
    tz = ZoneInfo("Asia/Tokyo")
    for w in out:
        # No voluntary window should fall on 5/11 (already a uni day).
        assert w.start.astimezone(tz).date() != date(2026, 5, 11)
    # Silence unused warning.
    assert timedelta
