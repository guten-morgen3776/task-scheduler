from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import User
from app.schemas.task import (
    TaskCreate,
    TaskMove,
    TaskRead,
    TaskReadWithSubtasks,
    TaskUpdate,
)
from app.services.tasks import tasks as tasks_service

list_scoped_router = APIRouter(prefix="/lists/{list_id}/tasks", tags=["tasks"])
task_router = APIRouter(prefix="/tasks", tags=["tasks"])


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "not_found", "message": "task not found"},
    )


def _list_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "not_found", "message": "list not found"},
    )


def _invalid_parent(msg: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"error": "validation_error", "message": msg},
    )


@list_scoped_router.get("", response_model=list[TaskRead])
async def list_tasks_in_list(
    list_id: str,
    include_completed: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TaskRead]:
    try:
        rows = await tasks_service.list_tasks(
            db, user.id, list_id, include_completed=include_completed
        )
    except tasks_service.ListNotFound as e:
        raise _list_not_found() from e
    return [TaskRead.model_validate(r) for r in rows]


@list_scoped_router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task_in_list(
    list_id: str,
    payload: TaskCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskRead:
    try:
        row = await tasks_service.create_task(
            db,
            user.id,
            list_id,
            title=payload.title,
            notes=payload.notes,
            parent_id=payload.parent_id,
            due=payload.due,
            duration_min=payload.duration_min,
            weight=payload.weight,
            priority=payload.priority,
            deadline=payload.deadline,
        )
    except tasks_service.ListNotFound as e:
        raise _list_not_found() from e
    except tasks_service.InvalidParent as e:
        raise _invalid_parent(str(e)) from e
    return TaskRead.model_validate(row)


@task_router.get("/{task_id}", response_model=TaskReadWithSubtasks)
async def get_task_endpoint(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskReadWithSubtasks:
    try:
        task = await tasks_service.get_task(db, user.id, task_id)
    except tasks_service.TaskNotFound as e:
        raise _not_found() from e
    subtasks = await tasks_service.get_subtasks(db, user.id, task.id)
    return TaskReadWithSubtasks(
        **TaskRead.model_validate(task).model_dump(),
        subtasks=[TaskRead.model_validate(s) for s in subtasks],
    )


@task_router.patch("/{task_id}", response_model=TaskRead)
async def update_task_endpoint(
    task_id: str,
    payload: TaskUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskRead:
    try:
        row = await tasks_service.update_task(
            db, user.id, task_id, **payload.model_dump(exclude_unset=True)
        )
    except tasks_service.TaskNotFound as e:
        raise _not_found() from e
    except tasks_service.InvalidParent as e:
        raise _invalid_parent(str(e)) from e
    return TaskRead.model_validate(row)


@task_router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task_endpoint(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    try:
        await tasks_service.delete_task(db, user.id, task_id)
    except tasks_service.TaskNotFound as e:
        raise _not_found() from e


@task_router.post("/{task_id}/complete", response_model=TaskRead)
async def complete_task_endpoint(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskRead:
    try:
        row = await tasks_service.complete_task(db, user.id, task_id)
    except tasks_service.TaskNotFound as e:
        raise _not_found() from e
    return TaskRead.model_validate(row)


@task_router.post("/{task_id}/uncomplete", response_model=TaskRead)
async def uncomplete_task_endpoint(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskRead:
    try:
        row = await tasks_service.uncomplete_task(db, user.id, task_id)
    except tasks_service.TaskNotFound as e:
        raise _not_found() from e
    return TaskRead.model_validate(row)


@task_router.post("/{task_id}/move", response_model=TaskRead)
async def move_task_endpoint(
    task_id: str,
    payload: TaskMove,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskRead:
    try:
        row = await tasks_service.move_task(
            db, user.id, task_id, list_id=payload.list_id, position=payload.position
        )
    except tasks_service.TaskNotFound as e:
        raise _not_found() from e
    except tasks_service.ListNotFound as e:
        raise _list_not_found() from e
    return TaskRead.model_validate(row)
