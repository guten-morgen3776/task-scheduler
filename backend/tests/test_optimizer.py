"""Scenario-driven tests for the MIP optimizer.

These cover the design's 7 expected behaviors plus a few edge cases.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.services.optimizer.config import OptimizerConfig
from app.services.optimizer.domain import OptimizerSlot, OptimizerTask
from app.services.optimizer.orchestrator import Optimizer


def _task(
    id: str,
    duration: int = 60,
    deadline: datetime | None = None,
    priority: int = 3,
    title: str = "t",
) -> OptimizerTask:
    return OptimizerTask(
        id=id,
        title=title,
        duration_min=duration,
        deadline=deadline,
        priority=priority,
    )


def _slot(
    id: str,
    start: datetime,
    duration: int = 60,
    energy: float = 0.7,
    duration_cap: int = 240,
    day_type: str = "normal",
    location: str = "anywhere",
) -> OptimizerSlot:
    return OptimizerSlot(
        id=id,
        start=start,
        duration_min=duration,
        energy_score=energy,
        allowed_max_task_duration_min=duration_cap,
        day_type=day_type,
        location=location,
    )


T0 = datetime(2026, 5, 11, 0, 0, tzinfo=UTC)


# ──────────────────────────────────────────────────────────────────────────
# Scenario 1: trivial — all tasks fit easily
# ──────────────────────────────────────────────────────────────────────────


def test_trivial_all_assigned() -> None:
    tasks = [_task(f"t{i}", duration=60, priority=3) for i in range(3)]
    slots = [_slot(f"s{i}", T0 + timedelta(hours=i), duration=120) for i in range(5)]
    result = Optimizer().solve(tasks, slots)
    assert result.status in {"optimal", "feasible"}
    assert result.unassigned_task_ids == []
    for a in result.assignments:
        assert a.total_assigned_min == 60


# ──────────────────────────────────────────────────────────────────────────
# Scenario 2: deadline pressure
# ──────────────────────────────────────────────────────────────────────────


def test_deadline_constraint_blocks_late_slots() -> None:
    early_deadline = T0 + timedelta(hours=2)
    tasks = [_task("urgent", duration=60, deadline=early_deadline, priority=5)]
    slots = [
        _slot("early", T0, duration=60),
        _slot("late", T0 + timedelta(hours=3), duration=60),  # ends 4h later, after deadline
    ]
    result = Optimizer().solve(tasks, slots)
    assert result.status in {"optimal", "feasible"}
    assignment = result.assignments[0]
    # Should be in the early slot, not the late one
    assert all(f.slot_id == "early" for f in assignment.fragments)


def test_no_slot_before_deadline_leads_to_unassigned() -> None:
    tasks = [_task("doomed", duration=60, deadline=T0, priority=5)]  # deadline at T0
    slots = [_slot("after", T0 + timedelta(hours=1), duration=60)]   # all slots after
    result = Optimizer().solve(tasks, slots)
    assert "doomed" in result.unassigned_task_ids


# ──────────────────────────────────────────────────────────────────────────
# Scenario 3: energy mismatch — heavy task needs low-cap slots only
# ──────────────────────────────────────────────────────────────────────────


def test_duration_cap_blocks_long_task() -> None:
    """A task longer than the slot's per-task duration cap can't be placed there."""
    tasks = [_task("long", duration=120, priority=4)]
    slots = [_slot("capped", T0, duration=120, duration_cap=60)]  # cap < task duration
    result = Optimizer().solve(tasks, slots)
    assert "long" in result.unassigned_task_ids


def test_long_task_prefers_high_energy_slot() -> None:
    """With energy_match weighted by minutes, the long task should claim the
    high-energy slot. Fragments may split with ties, so we only assert that
    the long task has at least one fragment in 'high'."""
    tasks = [
        _task("big", duration=60, priority=3),
        _task("small", duration=30, priority=3),
    ]
    slots = [
        _slot("high", T0, duration=60, energy=0.9),
        _slot("low", T0 + timedelta(hours=2), duration=90, energy=0.3),
    ]
    result = Optimizer().solve(tasks, slots)
    big = next(a for a in result.assignments if a.task_id == "big")
    big_minutes_in_high = sum(f.duration_min for f in big.fragments if f.slot_id == "high")
    # The long task should get at least half of its minutes in the high-energy slot
    assert big_minutes_in_high >= 30


# ──────────────────────────────────────────────────────────────────────────
# Scenario 4: overcapacity — not all tasks fit
# ──────────────────────────────────────────────────────────────────────────


def test_high_priority_wins_when_capacity_short() -> None:
    tasks = [
        _task("important", duration=60, priority=5),
        _task("trivial", duration=60, priority=1),
    ]
    slots = [_slot("only", T0, duration=60)]
    result = Optimizer().solve(tasks, slots)
    assert "important" not in result.unassigned_task_ids
    assert "trivial" in result.unassigned_task_ids


# ──────────────────────────────────────────────────────────────────────────
# Scenario 5: task split across slots
# ──────────────────────────────────────────────────────────────────────────


def test_long_task_split_across_slots() -> None:
    tasks = [_task("long", duration=180, priority=4)]
    slots = [
        _slot("a", T0, duration=60),
        _slot("b", T0 + timedelta(hours=2), duration=60),
        _slot("c", T0 + timedelta(hours=4), duration=60),
    ]
    result = Optimizer().solve(tasks, slots)
    a = result.assignments[0]
    assert a.total_assigned_min == 180
    assert len(a.fragments) == 3
    assert {f.slot_id for f in a.fragments} == {"a", "b", "c"}


# ──────────────────────────────────────────────────────────────────────────
# Scenario 6: min fragment size — small leftover dropped
# ──────────────────────────────────────────────────────────────────────────


def test_min_fragment_blocks_tiny_split() -> None:
    """Total slot capacity = 60, task = 60 with min_fragment 30. The two 30-min slots
    can each hold half the task and that's allowed."""
    tasks = [_task("split", duration=60, priority=4)]
    slots = [
        _slot("a", T0, duration=30),
        _slot("b", T0 + timedelta(hours=1), duration=30),
    ]
    result = Optimizer().solve(tasks, slots)
    a = result.assignments[0]
    assert a.total_assigned_min == 60
    assert len(a.fragments) == 2


def test_min_fragment_blocks_below_threshold() -> None:
    """Slot of 20 min < min_fragment 30 → cannot hold any portion → task unassigned."""
    tasks = [_task("t", duration=60, priority=4)]
    slots = [_slot("tiny", T0, duration=20)]  # 20 min < 30 min min_fragment
    result = Optimizer().solve(tasks, slots)
    assert "t" in result.unassigned_task_ids


# ──────────────────────────────────────────────────────────────────────────
# Scenario 7: max fragments per task
# ──────────────────────────────────────────────────────────────────────────


def test_max_fragments_respected() -> None:
    cfg = OptimizerConfig(max_fragments_per_task=2)
    # Task of 90 min, 6 slots of 30 min each → without limit could split 3 ways
    # With limit of 2 fragments, can't fit (need 90 / 2 = 45 min per fragment but slot=30)
    tasks = [_task("long", duration=90, priority=4)]
    slots = [_slot(f"s{i}", T0 + timedelta(hours=i), duration=30) for i in range(6)]
    result = Optimizer(config=cfg).solve(tasks, slots)
    assert "long" in result.unassigned_task_ids


# ──────────────────────────────────────────────────────────────────────────
# Misc edge cases
# ──────────────────────────────────────────────────────────────────────────


def test_empty_tasks_returns_empty_result() -> None:
    result = Optimizer().solve([], [])
    assert result.status == "optimal"
    assert result.assignments == []


def test_no_slots_means_all_unassigned() -> None:
    tasks = [_task("a", duration=60), _task("b", duration=30)]
    result = Optimizer().solve(tasks, [])
    assert set(result.unassigned_task_ids) == {"a", "b"}


def test_no_deadline_treated_as_unrestricted() -> None:
    tasks = [_task("flexible", duration=60, deadline=None, priority=3)]
    slots = [_slot("any", T0 + timedelta(days=365), duration=60)]
    result = Optimizer().solve(tasks, slots)
    assert "flexible" not in result.unassigned_task_ids


def test_slot_capacity_respected() -> None:
    """Two 60-min tasks + one 60-min slot → only one fits."""
    tasks = [_task("a", duration=60, priority=4), _task("b", duration=60, priority=2)]
    slots = [_slot("only", T0, duration=60)]
    result = Optimizer().solve(tasks, slots)
    assert len(result.unassigned_task_ids) == 1


def test_disabled_constraint_lets_violation_through() -> None:
    """With duration_cap disabled, a long task should fit in a low-cap slot."""
    cfg = OptimizerConfig(
        enabled_constraints={"all_or_nothing", "slot_capacity", "deadline", "min_fragment_size"}
    )
    tasks = [_task("long", duration=120, priority=4)]
    slots = [_slot("capped", T0, duration=120, duration_cap=60)]
    result = Optimizer(config=cfg).solve(tasks, slots)
    assert "long" not in result.unassigned_task_ids


def test_two_tasks_in_one_slot_get_sequential_offsets() -> None:
    """Regression: when two tasks pack into one slot, their fragments must be
    placed back-to-back, not both at slot.start.
    """
    tasks = [
        _task("a", duration=60, priority=3),
        _task("b", duration=60, priority=3),
    ]
    # 120-min slot, only one available — both tasks must share it.
    slots = [_slot("shared", T0, duration=120)]
    result = Optimizer().solve(tasks, slots)
    assert result.unassigned_task_ids == []
    starts: list[datetime] = []
    for a in result.assignments:
        for f in a.fragments:
            starts.append(f.start)
    assert len(starts) == 2
    # No two fragments should share the same start time.
    assert starts[0] != starts[1]
    # Both must lie within the slot bounds.
    slot_start = T0
    slot_end = T0 + timedelta(minutes=120)
    for s in starts:
        assert slot_start <= s < slot_end


def test_split_task_in_one_slot_does_not_overlap_neighbor() -> None:
    """A single 90-min task split into 60+30 inside one slot, sharing with another
    60-min task, should still produce non-overlapping fragments.
    """
    tasks = [
        _task("short", duration=60, priority=3),
        _task("long", duration=90, priority=3),
    ]
    slots = [_slot("big", T0, duration=150)]
    result = Optimizer().solve(tasks, slots)
    assert result.unassigned_task_ids == []
    intervals: list[tuple[datetime, datetime]] = []
    for a in result.assignments:
        for f in a.fragments:
            intervals.append((f.start, f.start + timedelta(minutes=f.duration_min)))
    intervals.sort()
    # No interval may overlap the next.
    for (_, end_a), (start_b, _) in zip(intervals, intervals[1:], strict=False):
        assert end_a <= start_b
