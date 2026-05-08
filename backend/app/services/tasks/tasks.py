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
    weight: float = 0.5,
    priority: int = 3,
    deadline=None,
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
        weight=weight,
        priority=priority,
        deadline=deadline,
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
        "weight",
        "priority",
        "deadline",
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
