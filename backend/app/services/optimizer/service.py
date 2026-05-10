"""High-level orchestration: pull tasks + slots, run optimizer, persist snapshot.

Bridges the API layer with the pure optimizer engine.
"""

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OptimizerSnapshot, Task
from app.services.optimizer.config import OptimizerConfig, OptimizerConfigUpdate
from app.services.optimizer.domain import OptimizerSlot, OptimizerTask, SolveResult
from app.services.optimizer.orchestrator import Optimizer
from app.services.slots import generator as slot_generator

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


async def _load_tasks(
    db: AsyncSession,
    user_id: str,
    list_ids: list[str] | None,
    task_ids: list[str] | None,
) -> list[OptimizerTask]:
    stmt = select(Task).where(Task.user_id == user_id, Task.completed.is_(False))
    if task_ids:
        stmt = stmt.where(Task.id.in_(task_ids))
    if list_ids:
        stmt = stmt.where(Task.list_id.in_(list_ids))
    rows = (await db.execute(stmt)).scalars().all()
    return [_task_to_optimizer_task(t) for t in rows]


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
    """Pull tasks/slots from DB, run MIP, persist snapshot. Returns (result, snapshot_id)."""
    tasks = await _load_tasks(db, user_id, list_ids, task_ids)
    if not tasks:
        raise NoTasksError("no incomplete tasks match the given filters")

    slots_pyd = await slot_generator.generate_slots(db, user_id, start=start, end=end)
    if not slots_pyd:
        raise NoSlotsError("no available slots in the given range")

    optimizer_slots = [
        OptimizerSlot(
            id=s.id,
            start=s.start,
            duration_min=s.duration_min,
            energy_score=s.energy_score,
            allowed_max_task_duration_min=s.allowed_max_task_duration_min,
            day_type=s.day_type,
            location=s.location,
        )
        for s in slots_pyd
    ]

    config = OptimizerConfig()
    if config_overrides is not None:
        config = config.merge(config_overrides)

    optimizer = Optimizer(config=config)
    result = optimizer.solve(tasks, optimizer_slots)

    snapshot_id = await _save_snapshot(
        db, user_id, tasks, optimizer_slots, config, result, note
    )
    return result, snapshot_id


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
