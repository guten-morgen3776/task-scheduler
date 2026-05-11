"""High-level orchestration: pull tasks + slots, run optimizer, persist snapshot.

Bridges the API layer with the pure optimizer engine.
"""

import logging
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OptimizerSnapshot, Task
from app.schemas.settings import (
    WEEKDAYS,
    Location,
    LocationCommute,
    SettingsRead,
)
from app.services.optimizer.config import OptimizerConfig, OptimizerConfigUpdate
from app.services.optimizer.domain import (
    Fragment,
    OptimizerSlot,
    OptimizerTask,
    SolveResult,
    TaskAssignment,
)
from app.services.optimizer.orchestrator import Optimizer
from app.services.slots import generator as slot_generator
from app.services.slots import settings as settings_service
from app.services.slots.domain import BusyPeriod, LocationWindow, Slot

logger = logging.getLogger("app.optimizer")


class OptimizerServiceError(Exception):
    pass


class NoTasksError(OptimizerServiceError):
    pass


class NoSlotsError(OptimizerServiceError):
    pass


def _task_to_optimizer_task(task: Task) -> OptimizerTask:
    return OptimizerTask(
        id=task.id,
        title=task.title,
        duration_min=task.duration_min,
        deadline=task.deadline,
        priority=task.priority,
        location=task.location,
    )


async def _load_raw_tasks(
    db: AsyncSession,
    user_id: str,
    list_ids: list[str] | None,
    task_ids: list[str] | None,
) -> list[Task]:
    stmt = select(Task).where(Task.user_id == user_id, Task.completed.is_(False))
    if task_ids:
        stmt = stmt.where(Task.id.in_(task_ids))
    if list_ids:
        stmt = stmt.where(Task.list_id.in_(list_ids))
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)


def _is_fixed(t: Task) -> bool:
    return bool(t.scheduled_fixed and t.scheduled_fragments)


def _fragments_to_busy(rows: list[Task]) -> list[BusyPeriod]:
    out: list[BusyPeriod] = []
    for r in rows:
        for f in r.scheduled_fragments or []:
            s = datetime.fromisoformat(f["start"])
            e = datetime.fromisoformat(f["end"])
            out.append(BusyPeriod(start=s, end=e, sources=(f"fixed:{r.id}",)))
    return out


def _build_fixed_assignments(rows: list[Task]) -> list[TaskAssignment]:
    out: list[TaskAssignment] = []
    for r in rows:
        if not r.scheduled_fragments:
            continue
        frags: list[Fragment] = []
        for i, f in enumerate(r.scheduled_fragments):
            s = datetime.fromisoformat(f["start"])
            e = datetime.fromisoformat(f["end"])
            dur = int((e - s).total_seconds() / 60)
            frags.append(
                Fragment(
                    task_id=r.id,
                    slot_id=f"fixed:{r.id}:{i}",
                    start=s,
                    duration_min=dur,
                )
            )
        frags.sort(key=lambda x: x.start)
        out.append(
            TaskAssignment(
                task_id=r.id,
                fragments=frags,
                total_assigned_min=sum(x.duration_min for x in frags),
            )
        )
    return out


def _parse_hhmm(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def _synthesize_voluntary_window(
    target_date: date,
    loc: Location,
    commute: LocationCommute,
    settings: SettingsRead,
    tz: ZoneInfo,
) -> LocationWindow | None:
    weekday = WEEKDAYS[target_date.weekday()]
    work_day = settings.work_hours.for_weekday(weekday)
    if not work_day.slots:
        return None
    first = datetime.combine(
        target_date, _parse_hhmm(work_day.slots[0].start), tzinfo=tz
    )
    last = datetime.combine(
        target_date, _parse_hhmm(work_day.slots[-1].end), tzinfo=tz
    )
    start_utc = (first - timedelta(minutes=commute.to_min)).astimezone(UTC)
    end_utc = (last + timedelta(minutes=commute.from_min)).astimezone(UTC)
    return LocationWindow(
        location=loc,
        start=start_utc,
        end=end_utc,
        commute_from_min=commute.from_min,
        commute_to_min=commute.to_min,
        is_voluntary=True,
    )


def _decide_voluntary_windows(
    flexible_tasks: list[OptimizerTask],
    initial_slots: list[Slot],
    settings: SettingsRead,
    start: datetime,
    end: datetime,
) -> list[LocationWindow]:
    """Greedy heuristic: synthesize voluntary visit windows on free days
    until each voluntary location's slot supply meets its task demand.
    """
    voluntary = [
        loc
        for loc in settings.voluntary_visit_locations
        if loc != "anywhere"
    ]
    if not voluntary:
        return []
    demand: dict[str, int] = {}
    for t in flexible_tasks:
        loc = t.location
        if loc and loc != "anywhere" and loc in voluntary:
            demand[loc] = demand.get(loc, 0) + t.duration_min
    if not demand:
        return []

    supply: dict[str, int] = {}
    for s in initial_slots:
        supply[s.location] = supply.get(s.location, 0) + s.duration_min

    tz = ZoneInfo(settings.work_hours.timezone)
    busy_day_keys: set[date] = {
        s.start.astimezone(tz).date()
        for s in initial_slots
        if s.location != "home"
    }
    start_date = start.astimezone(tz).date()
    end_date = end.astimezone(tz).date()

    out: list[LocationWindow] = []
    used_days: set[date] = set()
    for loc in voluntary:
        need = demand.get(loc, 0) - supply.get(loc, 0)
        if need <= 0:
            continue
        commute = settings.location_commutes.get(loc)
        if not commute:
            continue
        d = start_date
        while d <= end_date and need > 0:
            if d in busy_day_keys or d in used_days:
                d += timedelta(days=1)
                continue
            window = _synthesize_voluntary_window(d, loc, commute, settings, tz)
            if window is None:
                d += timedelta(days=1)
                continue
            out.append(window)
            used_days.add(d)
            free_min = int(
                (window.end - window.start).total_seconds() / 60
            ) - commute.to_min - commute.from_min
            need -= max(free_min, 0)
            d += timedelta(days=1)
    return out


async def run_optimization(
    db: AsyncSession,
    user_id: str,
    *,
    start: datetime,
    end: datetime,
    list_ids: list[str] | None = None,
    task_ids: list[str] | None = None,
    config_overrides: OptimizerConfigUpdate | None = None,
    note: str | None = None,
) -> tuple[SolveResult, str]:
    """Pull tasks/slots from DB, run MIP, persist snapshot. Returns (result, snapshot_id).

    Tasks with `scheduled_fixed=True` and existing fragments are excluded from
    the MIP — their placements are passed through unchanged. Their fragment
    time is also injected as busy so flexible tasks don't overlap them.

    If `settings.voluntary_visit_locations` is set and the corresponding tasks
    don't fit existing event-based windows, voluntary visit windows are added
    on free days to absorb the demand.
    """
    raw_tasks = await _load_raw_tasks(db, user_id, list_ids, task_ids)
    if not raw_tasks:
        raise NoTasksError("no incomplete tasks match the given filters")

    fixed_rows = [t for t in raw_tasks if _is_fixed(t)]
    flexible_rows = [t for t in raw_tasks if not _is_fixed(t)]
    fixed_tasks = [_task_to_optimizer_task(t) for t in fixed_rows]
    flexible_tasks = [_task_to_optimizer_task(t) for t in flexible_rows]

    settings = await settings_service.get_or_create_settings(db, user_id)
    fixed_busy = _fragments_to_busy(fixed_rows)

    initial_slots = await slot_generator.generate_slots(
        db,
        user_id,
        start=start,
        end=end,
        extra_busy_periods=fixed_busy,
        exclude_app_marked_events=True,
    )

    voluntary_windows = _decide_voluntary_windows(
        flexible_tasks, initial_slots, settings, start, end
    )

    config = OptimizerConfig()
    if config_overrides is not None:
        config = config.merge(config_overrides)

    async def _attempt(
        extend_until: str | None,
        *,
        disable_duration_cap: bool,
    ) -> tuple[list[OptimizerSlot], SolveResult]:
        slots_pyd_local = await slot_generator.generate_slots(
            db,
            user_id,
            start=start,
            end=end,
            extra_busy_periods=fixed_busy,
            extra_windows=voluntary_windows,
            exclude_app_marked_events=True,
            extend_work_hours_until=extend_until,
        )
        opt_slots = [
            OptimizerSlot(
                id=s.id,
                start=s.start,
                duration_min=s.duration_min,
                energy_score=s.energy_score,
                allowed_max_task_duration_min=s.allowed_max_task_duration_min,
                day_type=s.day_type,
                location=s.location,
            )
            for s in slots_pyd_local
        ]
        attempt_config = config
        if disable_duration_cap:
            relaxed = set(attempt_config.enabled_constraints)
            relaxed.discard("duration_cap")
            attempt_config = attempt_config.model_copy(
                update={"enabled_constraints": relaxed}
            )
        if flexible_tasks:
            res = Optimizer(config=attempt_config).solve(flexible_tasks, opt_slots)
        else:
            res = SolveResult(
                status="optimal",
                objective_value=0.0,
                assignments=[],
                unassigned_task_ids=[],
                solve_time_sec=0.0,
                notes=["only fixed tasks; MIP skipped"],
            )
        return opt_slots, res

    # Auto-retry with progressively more relaxed knobs so a deadline-heavy day
    # rarely trips force_deadlined. Order matters: cheapest relaxation first.
    #   1. standard work_hours
    #   2. extend evening to 23:30
    #   3. extend evening to 23:59
    #   4. extend to 23:59 AND drop duration_cap (last-resort; e.g., 4h task
    #      whose deadline lands on a heavy_day with cap 90min)
    attempts: list[tuple[str | None, bool, str]] = [
        (None, False, "standard"),
        ("23:30", False, "extend_2330"),
        ("23:59", False, "extend_2359"),
        ("23:59", True, "extend_2359_no_cap"),
    ]

    optimizer_slots: list[OptimizerSlot] = []
    flex_result: SolveResult | None = None
    used_label: str | None = None
    used_extension: str | None = None
    duration_cap_relaxed = False
    for extend_until, disable_cap, label in attempts:
        optimizer_slots, flex_result = await _attempt(
            extend_until, disable_duration_cap=disable_cap
        )
        if flexible_tasks and not optimizer_slots and extend_until is None:
            # Genuinely no slots even before extending — try the next attempt
            # (extension may add evening slots) before giving up.
            continue
        if flex_result.status != "infeasible":
            used_label = label
            used_extension = extend_until
            duration_cap_relaxed = disable_cap
            break

    if flex_result is None:
        raise OptimizerServiceError("optimization yielded no result")
    if flexible_tasks and not optimizer_slots and flex_result.status == "infeasible":
        raise NoSlotsError("no available slots in the given range")

    notes = list(flex_result.notes)
    if fixed_rows:
        notes.append(f"fixed_tasks_pass_through={len(fixed_rows)}")
    if voluntary_windows:
        notes.append(f"voluntary_visits_added={len(voluntary_windows)}")
    if used_extension is not None:
        notes.append(
            f"work_hours_extended_to={used_extension} (fallback to fit deadline tasks)"
        )
    if duration_cap_relaxed:
        notes.append(
            "duration_cap disabled as last resort — a task longer than the "
            "day's cap was forced through to honor its deadline"
        )
    _ = used_label  # retained for future telemetry
    merged = SolveResult(
        status=flex_result.status,
        objective_value=flex_result.objective_value,
        assignments=_build_fixed_assignments(fixed_rows) + flex_result.assignments,
        unassigned_task_ids=flex_result.unassigned_task_ids,
        solve_time_sec=flex_result.solve_time_sec,
        notes=notes,
    )

    snapshot_id = await _save_snapshot(
        db,
        user_id,
        fixed_tasks + flexible_tasks,
        optimizer_slots,
        config,
        merged,
        note,
    )
    return merged, snapshot_id


async def _save_snapshot(
    db: AsyncSession,
    user_id: str,
    tasks: list[OptimizerTask],
    slots: list[OptimizerSlot],
    config: OptimizerConfig,
    result: SolveResult,
    note: str | None,
) -> str:
    snapshot = OptimizerSnapshot(
        user_id=user_id,
        tasks_json=[_task_to_dict(t) for t in tasks],
        slots_json=[_slot_to_dict(s) for s in slots],
        config_json=config.model_dump(mode="json"),
        result_json=result.model_dump(mode="json"),
        note=note,
    )
    db.add(snapshot)
    await db.flush()
    return snapshot.id


def _task_to_dict(t: OptimizerTask) -> dict:
    return {
        "id": t.id,
        "title": t.title,
        "duration_min": t.duration_min,
        "deadline": t.deadline.isoformat() if t.deadline else None,
        "priority": t.priority,
        "location": t.location,
    }


def _slot_to_dict(s: OptimizerSlot) -> dict:
    return {
        "id": s.id,
        "start": s.start.isoformat(),
        "duration_min": s.duration_min,
        "energy_score": s.energy_score,
        "allowed_max_task_duration_min": s.allowed_max_task_duration_min,
        "day_type": s.day_type,
        "location": s.location,
    }


def _dict_to_task(d: dict) -> OptimizerTask:
    deadline = datetime.fromisoformat(d["deadline"]) if d["deadline"] else None
    return OptimizerTask(
        id=d["id"],
        title=d["title"],
        duration_min=d["duration_min"],
        deadline=deadline,
        priority=d["priority"],
        location=d.get("location"),
    )


def _dict_to_slot(d: dict) -> OptimizerSlot:
    return OptimizerSlot(
        id=d["id"],
        start=datetime.fromisoformat(d["start"]),
        duration_min=d["duration_min"],
        energy_score=d["energy_score"],
        allowed_max_task_duration_min=d["allowed_max_task_duration_min"],
        day_type=d["day_type"],
        location=d.get("location", "home"),
    )


async def list_snapshots(
    db: AsyncSession, user_id: str, limit: int = 50
) -> list[OptimizerSnapshot]:
    rows = (
        await db.execute(
            select(OptimizerSnapshot)
            .where(OptimizerSnapshot.user_id == user_id)
            .order_by(OptimizerSnapshot.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


async def get_snapshot(
    db: AsyncSession, user_id: str, snapshot_id: str
) -> OptimizerSnapshot | None:
    return (
        await db.execute(
            select(OptimizerSnapshot).where(
                OptimizerSnapshot.id == snapshot_id,
                OptimizerSnapshot.user_id == user_id,
            )
        )
    ).scalar_one_or_none()


async def delete_snapshot(
    db: AsyncSession, user_id: str, snapshot_id: str
) -> bool:
    snap = await get_snapshot(db, user_id, snapshot_id)
    if snap is None:
        return False
    await db.delete(snap)
    return True


async def apply_snapshot_to_tasks(
    db: AsyncSession, user_id: str, snapshot_id: str
) -> int:
    """Write scheduled_start / scheduled_end on tasks based on a snapshot's result.

    For each assigned task: scheduled_start = first fragment start,
    scheduled_end = last fragment end. Unassigned tasks are NOT cleared
    (re-running optimization with different inputs may keep them stale; the
    user can choose to clear via PATCH /tasks/{id}).

    Returns the number of tasks updated.
    """
    snap = await get_snapshot(db, user_id, snapshot_id)
    if snap is None:
        raise OptimizerServiceError(f"snapshot {snapshot_id} not found")

    result = snap.result_json
    if not result or not result.get("assignments"):
        return 0

    updated = 0
    for assignment in result["assignments"]:
        fragments = assignment.get("fragments") or []
        if not fragments:
            continue
        frag_records: list[dict] = []
        for f in fragments:
            start = datetime.fromisoformat(f["start"])
            end = start + _timedelta_min(f["duration_min"])
            frag_records.append(
                {"start": start.isoformat(), "end": end.isoformat()}
            )
        frag_records.sort(key=lambda x: x["start"])
        scheduled_start = datetime.fromisoformat(frag_records[0]["start"])
        scheduled_end = datetime.fromisoformat(frag_records[-1]["end"])

        task = (
            await db.execute(
                select(Task).where(Task.id == assignment["task_id"], Task.user_id == user_id)
            )
        ).scalar_one_or_none()
        if task is None:
            continue
        task.scheduled_start = scheduled_start
        task.scheduled_end = scheduled_end
        task.scheduled_fragments = frag_records
        updated += 1
    await db.flush()
    return updated


def _timedelta_min(minutes: int):
    from datetime import timedelta

    return timedelta(minutes=minutes)


async def replay_snapshot(
    db: AsyncSession,
    user_id: str,
    snapshot_id: str,
    *,
    config_overrides: OptimizerConfigUpdate | None = None,
    note: str | None = None,
) -> tuple[SolveResult, str]:
    snap = await get_snapshot(db, user_id, snapshot_id)
    if snap is None:
        raise OptimizerServiceError(f"snapshot {snapshot_id} not found")

    tasks = [_dict_to_task(d) for d in snap.tasks_json]
    slots = [_dict_to_slot(d) for d in snap.slots_json]
    base_config = OptimizerConfig.model_validate(snap.config_json)
    if config_overrides is not None:
        base_config = base_config.merge(config_overrides)

    optimizer = Optimizer(config=base_config)
    result = optimizer.solve(tasks, slots)

    new_id = await _save_snapshot(
        db, user_id, tasks, slots, base_config, result, note
    )
    return result, new_id
