from sqlalchemy import Integer, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task, TaskList
from app.services.tasks.positions import append_position


class TaskListNotFound(Exception):
    pass


async def list_lists(db: AsyncSession, user_id: str) -> list[tuple[TaskList, int, int]]:
    """Return rows of (TaskList, task_count, completed_count)."""
    rows = (
        await db.execute(
            select(TaskList)
            .where(TaskList.user_id == user_id)
            .order_by(TaskList.position)
        )
    ).scalars().all()

    counts: dict[str, tuple[int, int]] = {}
    if rows:
        ids = [r.id for r in rows]
        completed_int = case((Task.completed.is_(True), 1), else_=0).cast(Integer)
        agg = await db.execute(
            select(
                Task.list_id,
                func.count().label("total"),
                func.sum(completed_int).label("done"),
            )
            .where(Task.list_id.in_(ids))
            .group_by(Task.list_id)
        )
        for list_id, total, done in agg.all():
            counts[list_id] = (int(total or 0), int(done or 0))

    return [(r, *counts.get(r.id, (0, 0))) for r in rows]


async def get_list(db: AsyncSession, user_id: str, list_id: str) -> TaskList:
    row = (
        await db.execute(
            select(TaskList).where(TaskList.id == list_id, TaskList.user_id == user_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise TaskListNotFound(list_id)
    return row


async def create_list(db: AsyncSession, user_id: str, *, title: str) -> TaskList:
    existing_positions = (
        await db.execute(
            select(TaskList.position).where(TaskList.user_id == user_id)
        )
    ).scalars().all()
    new_list = TaskList(
        user_id=user_id,
        title=title,
        position=append_position(list(existing_positions)),
    )
    db.add(new_list)
    await db.flush()
    return new_list


async def update_list(
    db: AsyncSession,
    user_id: str,
    list_id: str,
    *,
    title: str | None = None,
    position: str | None = None,
) -> TaskList:
    row = await get_list(db, user_id, list_id)
    if title is not None:
        row.title = title
    if position is not None:
        row.position = position
    await db.flush()
    return row


async def delete_list(db: AsyncSession, user_id: str, list_id: str) -> None:
    row = await get_list(db, user_id, list_id)
    await db.delete(row)
