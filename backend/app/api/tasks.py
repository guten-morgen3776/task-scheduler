from datetime import datetime

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
from app.services.google import calendar as calendar_service
from app.services.google import oauth as oauth_service
from app.services.optimizer import writer as optimizer_writer
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
            priority=payload.priority,
            deadline=payload.deadline,
            location=payload.location,
        )
    except tasks_service.ListNotFound as e:
        raise _list_not_found() from e
    except tasks_service.InvalidParent as e:
        raise _invalid_parent(str(e)) from e
    return TaskRead.model_validate(row)


@task_router.get("/scheduled", response_model=list[TaskRead])
async def list_scheduled_tasks_endpoint(
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    include_completed: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TaskRead]:
    """Return tasks with `scheduled_start` set, ordered chronologically.

    Optional `start` / `end` (TZ-aware ISO 8601) filter the placement window.
    Completed tasks are omitted by default — set `include_completed=true` to
    include them.
    """
    if start is not None and start.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "validation_error", "message": "start must include a timezone"},
        )
    if end is not None and end.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "validation_error", "message": "end must include a timezone"},
        )
    rows = await tasks_service.list_scheduled_tasks(
        db, user.id, start=start, end=end, include_completed=include_completed
    )
    return [TaskRead.model_validate(r) for r in rows]


@task_router.post("/sync-from-calendar")
async def sync_from_calendar_endpoint(
    target_calendar_id: str = "primary",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Re-read app-marked events from Google Calendar and rewrite each task's
    scheduled_start / scheduled_end / scheduled_event_id from the truth there.

    Tasks whose stored event_id no longer exists on the calendar are cleared.
    """
    import asyncio

    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    try:
        creds = await oauth_service.load_credentials(db, user.id)
    except oauth_service.NotAuthenticatedError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "not_authenticated", "message": str(e)},
        ) from e
    except oauth_service.ReauthRequiredError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "reauth_required", "message": str(e)},
        ) from e

    def _fetch() -> list[dict]:
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        return optimizer_writer._list_app_events_sync(
            service, target_calendar_id, snapshot_id=None
        )

    try:
        events = await asyncio.get_running_loop().run_in_executor(None, _fetch)
    except HttpError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "calendar_api_error", "message": str(e)},
        ) from e
    except calendar_service.CalendarApiError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "calendar_api_error", "message": str(e)},
        ) from e

    updated, cleared = await tasks_service.sync_scheduled_from_calendar(
        db, user.id, events
    )
    return {
        "updated_task_count": updated,
        "cleared_task_count": cleared,
        "event_count": len(events),
    }


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
