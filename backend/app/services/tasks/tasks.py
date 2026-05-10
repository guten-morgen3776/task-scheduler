from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_now
from app.models import Task, TaskList
from app.services.tasks.positions import append_position


class TaskNotFound(Exception):
    pass


class ListNotFound(Exception):
    pass


class InvalidParent(Exception):
    pass


async def _ensure_list(db: AsyncSession, user_id: str, list_id: str) -> TaskList:
    row = (
        await db.execute(
            select(TaskList).where(TaskList.id == list_id, TaskList.user_id == user_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise ListNotFound(list_id)
    return row


async def list_tasks(
    db: AsyncSession,
    user_id: str,
    list_id: str,
    *,
    include_completed: bool = False,
) -> list[Task]:
    await _ensure_list(db, user_id, list_id)
    stmt = (
        select(Task)
        .where(Task.user_id == user_id, Task.list_id == list_id)
        .order_by(Task.position)
    )
    if not include_completed:
        stmt = stmt.where(Task.completed.is_(False))
    return list((await db.execute(stmt)).scalars().all())


async def list_scheduled_tasks(
    db: AsyncSession,
    user_id: str,
    *,
    start=None,
    end=None,
) -> list[Task]:
    """Tasks with a scheduled placement, optionally filtered by [start, end].

    Filtering is done on `scheduled_start`. Tasks without a placement are
    omitted. Completed tasks are included so the UI can show them as done.
    """
    stmt = (
        select(Task)
        .where(Task.user_id == user_id, Task.scheduled_start.is_not(None))
        .order_by(Task.scheduled_start)
    )
    if start is not None:
        stmt = stmt.where(Task.scheduled_start >= start)
    if end is not None:
        stmt = stmt.where(Task.scheduled_start < end)
    return list((await db.execute(stmt)).scalars().all())


async def sync_scheduled_from_calendar(
    db: AsyncSession,
    user_id: str,
    calendar_events: list,
) -> tuple[int, int]:
    """Reconcile tasks.scheduled_* fields from an authoritative list of
    app-marked Google Calendar events.

    `calendar_events` is the raw events.list() output, each dict carrying
    extendedProperties.private.task_id / fragment_index.

    For each task referenced by events:
      - scheduled_event_id = id of the fragment_index=0 event (or earliest)
      - scheduled_start    = min(event.start)
      - scheduled_end      = max(event.end)

    Tasks with a scheduled_event_id no longer present on the calendar have
    their scheduled_* fields cleared (the user deleted the event manually).

    Returns (updated_count, cleared_count).
    """
    from datetime import UTC, datetime

    # Group events by task_id.
    by_task: dict[str, list[dict]] = {}
    for ev in calendar_events:
        private = (ev.get("extendedProperties") or {}).get("private") or {}
        task_id = private.get("task_id")
        if not task_id:
            continue
        by_task.setdefault(task_id, []).append(ev)

    def _parse_dt(payload: dict) -> datetime:
        from dateutil import parser as date_parser
        raw = payload.get("dateTime") or payload.get("date")
        dt = date_parser.isoparse(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)

    updated = 0
    referenced_event_ids: set[str] = set()
    for task_id, events in by_task.items():
        # Pick the "primary" event: fragment_index=0 if present, else earliest start.
        events_sorted = sorted(events, key=lambda e: _parse_dt(e["start"]))
        primary = next(
            (
                e
                for e in events_sorted
                if (e.get("extendedProperties") or {}).get("private", {}).get(
                    "fragment_index"
                )
                == "0"
            ),
            events_sorted[0],
        )
        frag_records = [
            {
                "start": _parse_dt(e["start"]).isoformat(),
                "end": _parse_dt(e["end"]).isoformat(),
            }
            for e in events_sorted
        ]
        scheduled_start = datetime.fromisoformat(frag_records[0]["start"])
        scheduled_end = datetime.fromisoformat(frag_records[-1]["end"])

        task = (
            await db.execute(
                select(Task).where(Task.id == task_id, Task.user_id == user_id)
            )
        ).scalar_one_or_none()
        if task is None:
            continue
        task.scheduled_event_id = primary["id"]
        task.scheduled_start = scheduled_start
        task.scheduled_end = scheduled_end
        task.scheduled_fragments = frag_records
        updated += 1
        for e in events:
            referenced_event_ids.add(e["id"])

    # Clear scheduled_* for tasks whose stored event_id is not on the calendar.
    cleared = 0
    rows = (
        await db.execute(
            select(Task).where(
                Task.user_id == user_id,
                Task.scheduled_event_id.is_not(None),
            )
        )
    ).scalars().all()
    for t in rows:
        if t.scheduled_event_id not in referenced_event_ids:
            t.scheduled_event_id = None
            t.scheduled_start = None
            t.scheduled_end = None
            t.scheduled_fragments = None
            cleared += 1

    await db.flush()
    return updated, cleared


async def get_task(db: AsyncSession, user_id: str, task_id: str) -> Task:
    row = (
        await db.execute(select(Task).where(Task.id == task_id, Task.user_id == user_id))
    ).scalar_one_or_none()
    if row is None:
        raise TaskNotFound(task_id)
    return row


async def get_subtasks(db: AsyncSession, user_id: str, parent_id: str) -> list[Task]:
    rows = (
        await db.execute(
            select(Task)
            .where(Task.user_id == user_id, Task.parent_id == parent_id)
            .order_by(Task.position)
        )
    ).scalars().all()
    return list(rows)


async def create_task(
    db: AsyncSession,
    user_id: str,
    list_id: str,
    *,
    title: str,
    notes: str | None = None,
    parent_id: str | None = None,
    due=None,
    duration_min: int = 60,
    priority: int = 3,
    deadline=None,
    location: str | None = None,
) -> Task:
    await _ensure_list(db, user_id, list_id)

    if parent_id is not None:
        parent = (
            await db.execute(select(Task).where(Task.id == parent_id, Task.user_id == user_id))
        ).scalar_one_or_none()
        if parent is None:
            raise InvalidParent(f"parent {parent_id} not found")
        if parent.parent_id is not None:
            raise InvalidParent("nested subtasks (3+ levels) are not supported")
        if parent.list_id != list_id:
            raise InvalidParent("parent must be in the same list")

    existing = (
        await db.execute(
            select(Task.position).where(Task.user_id == user_id, Task.list_id == list_id)
        )
    ).scalars().all()

    task = Task(
        user_id=user_id,
        list_id=list_id,
        title=title,
        notes=notes,
        parent_id=parent_id,
        position=append_position(list(existing)),
        completed=False,
        due=due,
        duration_min=duration_min,
        priority=priority,
        deadline=deadline,
        location=location,
    )
    db.add(task)
    await db.flush()
    return task


async def update_task(
    db: AsyncSession,
    user_id: str,
    task_id: str,
    **fields,
) -> Task:
    task = await get_task(db, user_id, task_id)
    allowed = {
        "title",
        "notes",
        "parent_id",
        "due",
        "duration_min",
        "priority",
        "deadline",
        "location",
    }
    for key, value in fields.items():
        if key not in allowed or value is None:
            continue
        setattr(task, key, value)
    if "parent_id" in fields and fields["parent_id"] is not None:
        parent = (
            await db.execute(
                select(Task).where(
                    Task.id == fields["parent_id"], Task.user_id == user_id
                )
            )
        ).scalar_one_or_none()
        if parent is None:
            raise InvalidParent(f"parent {fields['parent_id']} not found")
        if parent.parent_id is not None:
            raise InvalidParent("nested subtasks not supported")
        if parent.list_id != task.list_id:
            raise InvalidParent("parent must be in the same list")
    await db.flush()
    return task


async def complete_task(db: AsyncSession, user_id: str, task_id: str) -> Task:
    task = await get_task(db, user_id, task_id)
    if not task.completed:
        task.completed = True
        task.completed_at = utc_now()
        await db.flush()
    return task


async def uncomplete_task(db: AsyncSession, user_id: str, task_id: str) -> Task:
    task = await get_task(db, user_id, task_id)
    if task.completed:
        task.completed = False
        task.completed_at = None
        await db.flush()
    return task


async def move_task(
    db: AsyncSession,
    user_id: str,
    task_id: str,
    *,
    list_id: str | None = None,
    position: str | None = None,
) -> Task:
    task = await get_task(db, user_id, task_id)
    if list_id is not None and list_id != task.list_id:
        await _ensure_list(db, user_id, list_id)
        task.list_id = list_id
        if position is None:
            existing = (
                await db.execute(
                    select(Task.position).where(
                        Task.user_id == user_id, Task.list_id == list_id
                    )
                )
            ).scalars().all()
            task.position = append_position(list(existing))
    if position is not None:
        task.position = position
    await db.flush()
    return task


async def delete_task(db: AsyncSession, user_id: str, task_id: str) -> None:
    task = await get_task(db, user_id, task_id)
    await db.delete(task)
