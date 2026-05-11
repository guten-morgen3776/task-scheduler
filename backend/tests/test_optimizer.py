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


def test_no_slot_before_deadline_makes_model_infeasible() -> None:
    """Deadline tasks MUST be placed pre-deadline; if no slot fits, the model
    is infeasible (it doesn't silently leave the task unassigned)."""
    tasks = [
        _task("doomed", duration=60, deadline=T0, priority=5, title="doomed-report"),
    ]
    slots = [_slot("after", T0 + timedelta(hours=1), duration=60)]
    result = Optimizer().solve(tasks, slots)
    assert result.status == "infeasible"
    # Diagnostic note pinpoints the offending task by title.
    assert any("doomed-report" in n for n in result.notes)


def test_deadline_task_with_no_slot_forces_infeasible_even_with_other_options() -> None:
    """One impossible-to-place deadline task crashes the whole solve even if
    other deadline-less tasks could have been placed — by design (絶対条件)."""
    tasks = [
        _task("doomed", duration=60, deadline=T0, priority=5),
        _task("flexible", duration=60, deadline=None, priority=3),
    ]
    slots = [_slot("after", T0 + timedelta(hours=1), duration=120)]
    result = Optimizer().solve(tasks, slots)
    assert result.status == "infeasible"


def test_deadline_task_that_fits_is_still_placed() -> None:
    tasks = [_task("urgent", duration=60, deadline=T0 + timedelta(hours=2), priority=5)]
    slots = [_slot("early", T0, duration=60)]
    result = Optimizer().solve(tasks, slots)
    assert result.status in {"optimal", "feasible"}
    assert result.unassigned_task_ids == []


def test_no_deadline_task_can_still_be_unassigned() -> None:
    """The new hard constraint applies only to tasks WITH a deadline. Tasks
    without one may still go unassigned if there isn't room."""
    tasks = [
        _task("a", duration=60, deadline=None, priority=3),
        _task("b", duration=60, deadline=None, priority=3),
    ]
    slots = [_slot("only", T0, duration=60)]  # room for one
    result = Optimizer().solve(tasks, slots)
    assert result.status in {"optimal", "feasible"}
    assert len(result.unassigned_task_ids) == 1


def test_low_energy_extension_slot_still_lets_deadline_task_fit() -> None:
    """Extended (evening fallback) slots have a low energy_score so the
    optimizer only uses them when no regular slot fits. A deadlined task
    that only fits in such a slot must still be placed."""
    deadline = T0 + timedelta(hours=2)
    tasks = [_task("urgent", duration=60, deadline=deadline, priority=5)]
    slots = [_slot("evening", T0, duration=60, energy=0.21)]  # extension multiplier ≈ 0.3 × 0.7
    result = Optimizer().solve(tasks, slots)
    assert result.status in {"optimal", "feasible"}
    assert result.unassigned_task_ids == []


def test_duration_cap_blocks_long_task_when_enabled() -> None:
    """4h task on a slot whose cap is 90 min → can't be placed (duration_cap)."""
    tasks = [_task("long", duration=240, deadline=T0 + timedelta(hours=6), priority=5)]
    slots = [_slot("capped", T0, duration=360, duration_cap=90)]
    result = Optimizer().solve(tasks, slots)
    assert result.status == "infeasible"


def test_keep_together_prefers_single_slot_over_split() -> None:
    """When a task fits in one slot, the optimizer should not split it
    just because the duration also fits across two smaller slots."""
    tasks = [_task("a", duration=60, priority=3)]
    slots = [
        _slot("big", T0, duration=60),
        _slot("split1", T0 + timedelta(hours=2), duration=30),
        _slot("split2", T0 + timedelta(hours=3), duration=30),
    ]
    result = Optimizer().solve(tasks, slots)
    assert result.status in {"optimal", "feasible"}
    assignment = result.assignments[0]
    assert len(assignment.fragments) == 1
    assert assignment.fragments[0].slot_id == "big"


def test_keep_together_avoids_co_splitting_when_one_task_fits_whole() -> None:
    """Regression for the 5/12 scenario: two tasks on a day with limited
    high-energy slots + a low-energy fallback (extension). The optimizer used
    to split BOTH tasks to maximize energy_match. With the strengthened
    keep_together weight, it should keep the smaller task whole and only
    split the one that physically must.
    """
    # Two normal-energy slots and one low-energy fallback (extension).
    slots = [
        _slot("normal-1", T0, duration=115, energy=0.7),
        _slot("normal-2", T0 + timedelta(hours=3), duration=120, energy=0.7),
        _slot("extension", T0 + timedelta(hours=6), duration=120, energy=0.21),
    ]
    # 住環境 (180 min) cannot fit in one slot (max single = 120). 現代国際社会論
    # (90 min) fits whole in normal-1.
    tasks = [
        _task("housing", duration=180, priority=4),
        _task("intl", duration=90, priority=4),
    ]
    result = Optimizer().solve(tasks, slots)
    assert result.status in {"optimal", "feasible"}
    assignments = {a.task_id: a for a in result.assignments}
    # 現代国際社会論 should not be split (90 min fits in one slot).
    assert len(assignments["intl"].fragments) == 1
    # 住環境 has to split since 180 > 120 max slot, but it should be exactly 2.
    assert len(assignments["housing"].fragments) == 2


def test_keep_together_prefers_same_day_over_multi_day() -> None:
    """Given the choice of putting a 90-min task entirely in one day's slots
    vs spreading it across two days, the optimizer should keep it on one day."""
    day1_morning = T0
    day1_afternoon = T0 + timedelta(hours=4)
    day2_morning = T0 + timedelta(days=1)
    tasks = [_task("a", duration=90, priority=3)]
    slots = [
        _slot("d1-am", day1_morning, duration=60),
        _slot("d1-pm", day1_afternoon, duration=60),
        _slot("d2-am", day2_morning, duration=60),
    ]
    result = Optimizer().solve(tasks, slots)
    assert result.status in {"optimal", "feasible"}
    assignment = result.assignments[0]
    slot_ids_used = {f.slot_id for f in assignment.fragments}
    assert slot_ids_used == {"d1-am", "d1-pm"}, (
        f"expected the same-day pair (d1-am, d1-pm), got {slot_ids_used}"
    )


def test_early_placement_prefers_earlier_slot_when_other_factors_equal() -> None:
    """With everything else equal (same energy, same location, same day_type),
    a deadlined task should land in the earlier of two candidate slots."""
    deadline = T0 + timedelta(days=7)
    tasks = [_task("a", duration=60, deadline=deadline, priority=3)]
    slots = [
        _slot("early", T0, duration=60, energy=0.7),
        _slot("late", T0 + timedelta(days=5), duration=60, energy=0.7),
    ]
    result = Optimizer().solve(tasks, slots)
    assert result.status in {"optimal", "feasible"}
    assert result.assignments[0].fragments[0].slot_id == "early"


def test_early_placement_inactive_for_tasks_without_deadline() -> None:
    """Without a deadline there's no concept of "earliness". The objective
    must not contribute and the placement choice falls back to energy_match
    / priority / keep_together. With equal energy slots, either is fine."""
    tasks = [_task("a", duration=60, deadline=None, priority=3)]
    slots = [
        _slot("early", T0, duration=60, energy=0.7),
        _slot("late", T0 + timedelta(days=5), duration=60, energy=0.7),
    ]
    result = Optimizer().solve(tasks, slots)
    assert result.status in {"optimal", "feasible"}
    chosen = result.assignments[0].fragments[0].slot_id
    assert chosen in {"early", "late"}


def test_early_placement_yields_to_strong_energy_match() -> None:
    """A large energy_match gain should still win over early_placement —
    earliness is soft and shouldn't override "actually do hard work when
    you're fresh"."""
    deadline = T0 + timedelta(days=7)
    tasks = [_task("a", duration=60, deadline=deadline, priority=3)]
    slots = [
        # Early but very low-energy
        _slot("early_lowE", T0, duration=60, energy=0.1),
        # Later but high-energy
        _slot("late_highE", T0 + timedelta(days=5), duration=60, energy=1.0),
    ]
    result = Optimizer().solve(tasks, slots)
    assert result.status in {"optimal", "feasible"}
    assert result.assignments[0].fragments[0].slot_id == "late_highE"


def test_disabled_duration_cap_lets_over_cap_task_fit() -> None:
    """With duration_cap disabled (last-resort relaxation in the retry chain),
    the same 4h task can be placed in the same capped slot."""
    cfg = OptimizerConfig(
        enabled_constraints={
            "all_or_nothing",
            "slot_capacity",
            "deadline",
            "force_deadlined",
            "min_fragment_size",
            "max_fragments",
            "location_compatibility",
            # duration_cap intentionally omitted
        }
    )
    tasks = [_task("long", duration=240, deadline=T0 + timedelta(hours=6), priority=5)]
    slots = [_slot("capped", T0, duration=360, duration_cap=90)]
    result = Optimizer(config=cfg).solve(tasks, slots)
    assert result.status in {"optimal", "feasible"}
    assert result.unassigned_task_ids == []


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
