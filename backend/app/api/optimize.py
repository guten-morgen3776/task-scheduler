from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import Task, User
from app.schemas.optimizer import (
    DeleteWriteResponse,
    FragmentRead,
    OptimizeRequest,
    OptimizeResponse,
    ReplayRequest,
    SnapshotDetail,
    SnapshotSummary,
    TaskAssignmentRead,
    UnassignedRead,
    WriteRequest,
    WriteResponse,
    WrittenEventRead,
)
from app.services.event_log import record as record_event
from app.services.google import calendar as calendar_service
from app.services.google import oauth as oauth_service
from app.services.optimizer import service as optimizer_service
from app.services.optimizer import writer as optimizer_writer
from app.services.optimizer.domain import SolveResult

optimize_router = APIRouter(tags=["optimizer"])
snapshots_router = APIRouter(prefix="/optimizer/snapshots", tags=["optimizer"])


async def _build_response(
    db: AsyncSession,
    user_id: str,
    result: SolveResult,
    snapshot_id: str,
) -> OptimizeResponse:
    from sqlalchemy import select

    # Lookup task titles for friendlier output. Use a single query for all referenced ids.
    referenced_ids = [a.task_id for a in result.assignments] + result.unassigned_task_ids
    title_map: dict[str, str] = {}
    if referenced_ids:
        rows = (
            await db.execute(
                select(Task.id, Task.title).where(
                    Task.id.in_(referenced_ids), Task.user_id == user_id
                )
            )
        ).all()
        title_map = {row.id: row.title for row in rows}

    assignments = [
        TaskAssignmentRead(
            task_id=a.task_id,
            task_title=title_map.get(a.task_id, "(unknown)"),
            fragments=[FragmentRead(**f.model_dump()) for f in a.fragments],
            total_assigned_min=a.total_assigned_min,
        )
        for a in result.assignments
        if a.fragments
    ]
    unassigned = [
        UnassignedRead(task_id=tid, task_title=title_map.get(tid, "(unknown)"))
        for tid in result.unassigned_task_ids
    ]
    return OptimizeResponse(
        status=result.status,
        objective_value=result.objective_value,
        snapshot_id=snapshot_id,
        assignments=assignments,
        unassigned=unassigned,
        solve_time_sec=result.solve_time_sec,
        notes=result.notes,
    )


@optimize_router.post("/optimize", response_model=OptimizeResponse)
async def optimize(
    payload: OptimizeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OptimizeResponse:
    if payload.start.tzinfo is None or payload.end.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "validation_error",
                "message": "start and end must include a timezone offset",
            },
        )
    if payload.end <= payload.start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "validation_error", "message": "end must be after start"},
        )
    try:
        result, snapshot_id = await optimizer_service.run_optimization(
            db,
            user.id,
            start=payload.start,
            end=payload.end,
            list_ids=payload.list_ids,
            task_ids=payload.task_ids,
            config_overrides=payload.config_overrides,
            note=payload.note,
        )
    except optimizer_service.NoTasksError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "no_tasks", "message": str(e)},
        ) from e
    except optimizer_service.NoSlotsError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "no_slots", "message": str(e)},
        ) from e
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
    except calendar_service.CalendarApiError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "calendar_api_error", "message": str(e)},
        ) from e
    await record_event(
        db, user.id, "optimize.ran",
        subject_type="snapshot", subject_id=snapshot_id,
        payload={
            "status": result.status,
            "objective_value": result.objective_value,
            "solve_time_sec": result.solve_time_sec,
            "assigned_count": len(result.assignments),
            "unassigned_count": len(result.unassigned_task_ids),
            "config_overrides": (
                payload.config_overrides.model_dump(exclude_unset=True)
                if payload.config_overrides
                else None
            ),
        },
    )
    return await _build_response(db, user.id, result, snapshot_id)


@snapshots_router.get("", response_model=list[SnapshotSummary])
async def list_snapshots(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[SnapshotSummary]:
    rows = await optimizer_service.list_snapshots(db, user.id)
    return [
        SnapshotSummary(
            id=r.id,
            created_at=r.created_at,
            note=r.note,
            status=(r.result_json or {}).get("status") if r.result_json else None,
            task_count=len(r.tasks_json or []),
            slot_count=len(r.slots_json or []),
        )
        for r in rows
    ]


@snapshots_router.get("/{snapshot_id}", response_model=SnapshotDetail)
async def get_snapshot(
    snapshot_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SnapshotDetail:
    snap = await optimizer_service.get_snapshot(db, user.id, snapshot_id)
    if snap is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": "snapshot not found"},
        )
    return SnapshotDetail(
        id=snap.id,
        created_at=snap.created_at,
        note=snap.note,
        tasks_json=snap.tasks_json,
        slots_json=snap.slots_json,
        config_json=snap.config_json,
        result_json=snap.result_json,
    )


@snapshots_router.delete("/{snapshot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_snapshot(
    snapshot_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    deleted = await optimizer_service.delete_snapshot(db, user.id, snapshot_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": "snapshot not found"},
        )


@snapshots_router.post("/{snapshot_id}/replay", response_model=OptimizeResponse)
async def replay_snapshot(
    snapshot_id: str,
    payload: ReplayRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OptimizeResponse:
    try:
        result, new_id = await optimizer_service.replay_snapshot(
            db,
            user.id,
            snapshot_id,
            config_overrides=payload.config_overrides,
            note=payload.note,
        )
    except optimizer_service.OptimizerServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": str(e)},
        ) from e
    return await _build_response(db, user.id, result, new_id)


@snapshots_router.post("/{snapshot_id}/apply")
async def apply_snapshot(
    snapshot_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Write scheduled_start / scheduled_end on tasks based on the snapshot's result.

    The user clicks /complete on each task by its scheduled_end; whatever isn't
    completed by then is treated as not-done at next /optimize.
    """
    try:
        updated = await optimizer_service.apply_snapshot_to_tasks(
            db, user.id, snapshot_id
        )
    except optimizer_service.OptimizerServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": str(e)},
        ) from e
    await record_event(
        db, user.id, "snapshot.applied",
        subject_type="snapshot", subject_id=snapshot_id,
        payload={"updated_task_count": updated},
    )
    return {"updated_task_count": updated, "snapshot_id": snapshot_id}


@snapshots_router.post("/{snapshot_id}/write", response_model=WriteResponse)
async def write_snapshot_to_calendar(
    snapshot_id: str,
    payload: WriteRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WriteResponse:
    req = payload or WriteRequest()
    try:
        result = await optimizer_writer.write_snapshot(
            db,
            user.id,
            snapshot_id,
            dry_run=req.dry_run,
            target_calendar_id=req.target_calendar_id,
        )
    except optimizer_writer.SnapshotNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": str(e)},
        ) from e
    except optimizer_writer.NothingToWriteError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "nothing_to_write", "message": str(e)},
        ) from e
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
    except calendar_service.CalendarApiError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "calendar_api_error", "message": str(e)},
        ) from e
    await record_event(
        db, user.id, "snapshot.written",
        subject_type="snapshot", subject_id=result.snapshot_id,
        payload={
            "dry_run": result.dry_run,
            "target_calendar_id": result.target_calendar_id,
            "deleted_event_count": result.deleted_event_count,
            "created_event_count": len(result.created_events),
        },
    )
    return WriteResponse(
        snapshot_id=result.snapshot_id,
        dry_run=result.dry_run,
        target_calendar_id=result.target_calendar_id,
        deleted_event_count=result.deleted_event_count,
        created_events=[
            WrittenEventRead(
                task_id=ev.task_id,
                task_title=ev.task_title,
                event_id=ev.event_id,
                start=ev.start,
                end=ev.end,
                fragment_index=ev.fragment_index,
            )
            for ev in result.created_events
        ],
    )


@snapshots_router.delete(
    "/{snapshot_id}/write", response_model=DeleteWriteResponse
)
async def delete_snapshot_calendar_events(
    snapshot_id: str,
    target_calendar_id: str = "primary",
    only_this_snapshot: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DeleteWriteResponse:
    """Delete events written by this app.

    By default deletes ALL app-marked events on the target calendar. Pass
    `only_this_snapshot=true` to restrict deletion to events tagged with the
    given snapshot_id.
    """
    try:
        deleted = await optimizer_writer.delete_all_app_events(
            db,
            user.id,
            target_calendar_id=target_calendar_id,
            snapshot_id=snapshot_id if only_this_snapshot else None,
        )
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
    except calendar_service.CalendarApiError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "calendar_api_error", "message": str(e)},
        ) from e
    await record_event(
        db, user.id, "snapshot.write_deleted",
        subject_type="snapshot",
        subject_id=snapshot_id if only_this_snapshot else None,
        payload={
            "deleted_event_count": deleted,
            "target_calendar_id": target_calendar_id,
            "only_this_snapshot": only_this_snapshot,
        },
    )
    return DeleteWriteResponse(
        deleted_event_count=deleted, target_calendar_id=target_calendar_id
    )
