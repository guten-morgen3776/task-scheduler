from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import User
from app.schemas.task_list import TaskListCreate, TaskListReadWithCounts, TaskListUpdate
from app.services.tasks import lists as lists_service

router = APIRouter(prefix="/lists", tags=["lists"])


@router.get("", response_model=list[TaskListReadWithCounts])
async def list_lists(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TaskListReadWithCounts]:
    rows = await lists_service.list_lists(db, user.id)
    return [
        TaskListReadWithCounts(
            id=row.id,
            title=row.title,
            position=row.position,
            created_at=row.created_at,
            updated_at=row.updated_at,
            task_count=task_count,
            completed_count=completed_count,
        )
        for row, task_count, completed_count in rows
    ]


@router.post("", response_model=TaskListReadWithCounts, status_code=status.HTTP_201_CREATED)
async def create_list(
    payload: TaskListCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskListReadWithCounts:
    row = await lists_service.create_list(db, user.id, title=payload.title)
    return TaskListReadWithCounts(
        id=row.id,
        title=row.title,
        position=row.position,
        created_at=row.created_at,
        updated_at=row.updated_at,
        task_count=0,
        completed_count=0,
    )


@router.get("/{list_id}", response_model=TaskListReadWithCounts)
async def get_list_endpoint(
    list_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskListReadWithCounts:
    try:
        rows = await lists_service.list_lists(db, user.id)
    except lists_service.TaskListNotFound as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": "list not found"},
        ) from e
    for row, task_count, completed_count in rows:
        if row.id == list_id:
            return TaskListReadWithCounts(
                id=row.id,
                title=row.title,
                position=row.position,
                created_at=row.created_at,
                updated_at=row.updated_at,
                task_count=task_count,
                completed_count=completed_count,
            )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "not_found", "message": "list not found"},
    )


@router.patch("/{list_id}", response_model=TaskListReadWithCounts)
async def update_list(
    list_id: str,
    payload: TaskListUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskListReadWithCounts:
    try:
        row = await lists_service.update_list(
            db, user.id, list_id, title=payload.title, position=payload.position
        )
    except lists_service.TaskListNotFound as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": "list not found"},
        ) from e
    return TaskListReadWithCounts(
        id=row.id,
        title=row.title,
        position=row.position,
        created_at=row.created_at,
        updated_at=row.updated_at,
        task_count=0,
        completed_count=0,
    )


@router.delete("/{list_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_list(
    list_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    try:
        await lists_service.delete_list(db, user.id, list_id)
    except lists_service.TaskListNotFound as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": "list not found"},
        ) from e
