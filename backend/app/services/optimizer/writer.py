"""Phase 5: write a snapshot's assignments to Google Calendar as events.

Each fragment of an assigned task becomes one event in the target calendar.
Events are tagged via `extendedProperties.private.task_scheduler="1"` so
re-runs can identify and remove the previous batch (delete-then-create).

Re-write strategy:
  1. List all events with the `task_scheduler=1` marker on the target calendar.
  2. Delete them all.
  3. Insert new events from the snapshot's assignments.
  4. Update tasks.scheduled_event_id to the first fragment's event id.

dry_run mode skips the destructive Google API calls but still returns what
would happen.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OptimizerSnapshot, Task
from app.services.google import oauth as oauth_service
from app.services.google.calendar import CalendarApiError

logger = logging.getLogger("app.optimizer.writer")

APP_MARKER_KEY = "task_scheduler"
APP_MARKER_VALUE = "1"
TZ_NAME = "Asia/Tokyo"
EVENT_TITLE_PREFIX = "[task-scheduler]"


class WriteError(Exception):
    pass


class SnapshotNotFoundError(WriteError):
    pass


class NothingToWriteError(WriteError):
    pass


@dataclass(frozen=True)
class WrittenEvent:
    task_id: str
    task_title: str
    event_id: str | None  # None when dry_run=True
    start: datetime
    end: datetime
    fragment_index: int


@dataclass(frozen=True)
class WriteResult:
    snapshot_id: str
    dry_run: bool
    deleted_event_count: int
    created_events: list[WrittenEvent]
    target_calendar_id: str


def _build_event_body(
    *,
    task_id: str,
    task_title: str,
    snapshot_id: str,
    fragment_index: int,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    return {
        "summary": f"{EVENT_TITLE_PREFIX} {task_title}",
        "description": f"Optimized by task-scheduler. Snapshot: {snapshot_id}",
        "start": {"dateTime": start.isoformat(), "timeZone": TZ_NAME},
        "end": {"dateTime": end.isoformat(), "timeZone": TZ_NAME},
        "extendedProperties": {
            "private": {
                APP_MARKER_KEY: APP_MARKER_VALUE,
                "snapshot_id": snapshot_id,
                "task_id": task_id,
                "fragment_index": str(fragment_index),
            }
        },
        # Suppress notifications. The app may write many events at once and
        # default reminders would spam the user's phone.
        "reminders": {"useDefault": False, "overrides": []},
    }


def _list_app_events_sync(
    service: Any,
    calendar_id: str,
    snapshot_id: str | None = None,
) -> list[dict[str, Any]]:
    """List events on the target calendar that carry the app marker.

    If `snapshot_id` is given, narrow the result to only events belonging to
    that snapshot. Multiple privateExtendedProperty filters are AND-combined
    by the API.
    """
    private_filters = [f"{APP_MARKER_KEY}={APP_MARKER_VALUE}"]
    if snapshot_id is not None:
        private_filters.append(f"snapshot_id={snapshot_id}")

    items: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        resp = (
            service.events()
            .list(
                calendarId=calendar_id,
                privateExtendedProperty=private_filters,
                showDeleted=False,
                singleEvents=True,
                maxResults=2500,
                pageToken=page_token,
            )
            .execute()
        )
        items.extend(resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return items


def _delete_events_sync(
    service: Any, calendar_id: str, event_ids: list[str]
) -> int:
    deleted = 0
    for eid in event_ids:
        try:
            service.events().delete(
                calendarId=calendar_id, eventId=eid
            ).execute()
            deleted += 1
        except HttpError as e:
            # 410 Gone (already deleted) is benign — count as deleted.
            if e.resp.status == 410:
                deleted += 1
                continue
            raise
    return deleted


def _insert_events_sync(
    service: Any, calendar_id: str, bodies: list[dict[str, Any]]
) -> list[str]:
    ids: list[str] = []
    for body in bodies:
        created = (
            service.events()
            .insert(calendarId=calendar_id, body=body)
            .execute()
        )
        ids.append(created["id"])
    return ids


async def _load_snapshot(
    db: AsyncSession, user_id: str, snapshot_id: str
) -> OptimizerSnapshot:
    snap = (
        await db.execute(
            select(OptimizerSnapshot).where(
                OptimizerSnapshot.id == snapshot_id,
                OptimizerSnapshot.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if snap is None:
        raise SnapshotNotFoundError(f"snapshot {snapshot_id} not found")
    return snap


def _title_map(snapshot: OptimizerSnapshot) -> dict[str, str]:
    return {t["id"]: t.get("title", "(unknown)") for t in (snapshot.tasks_json or [])}


def _planned_events(
    snapshot: OptimizerSnapshot,
) -> list[tuple[str, str, int, datetime, datetime]]:
    """Return (task_id, task_title, fragment_index, start, end) for each fragment."""
    result = snapshot.result_json or {}
    titles = _title_map(snapshot)
    out: list[tuple[str, str, int, datetime, datetime]] = []
    for assignment in result.get("assignments") or []:
        task_id = assignment["task_id"]
        task_title = titles.get(task_id, "(unknown)")
        for idx, frag in enumerate(assignment.get("fragments") or []):
            start = datetime.fromisoformat(frag["start"])
            end = start + timedelta(minutes=int(frag["duration_min"]))
            out.append((task_id, task_title, idx, start, end))
    return out


async def _update_scheduled_event_ids(
    db: AsyncSession,
    user_id: str,
    *,
    first_event_id_by_task: dict[str, str],
) -> None:
    if not first_event_id_by_task:
        return
    rows = (
        await db.execute(
            select(Task).where(
                Task.user_id == user_id,
                Task.id.in_(list(first_event_id_by_task.keys())),
            )
        )
    ).scalars().all()
    for task in rows:
        task.scheduled_event_id = first_event_id_by_task[task.id]
    await db.flush()


async def _clear_scheduled_event_ids_for_app_events(
    db: AsyncSession, user_id: str, deleted_event_ids: set[str]
) -> None:
    """Clear scheduled_event_id on tasks whose stored event_id was just deleted."""
    if not deleted_event_ids:
        return
    rows = (
        await db.execute(
            select(Task).where(
                Task.user_id == user_id,
                Task.scheduled_event_id.in_(list(deleted_event_ids)),
            )
        )
    ).scalars().all()
    for task in rows:
        task.scheduled_event_id = None
    await db.flush()


async def write_snapshot(
    db: AsyncSession,
    user_id: str,
    snapshot_id: str,
    *,
    dry_run: bool = False,
    target_calendar_id: str = "primary",
) -> WriteResult:
    snapshot = await _load_snapshot(db, user_id, snapshot_id)
    planned = _planned_events(snapshot)
    if not planned:
        raise NothingToWriteError(
            f"snapshot {snapshot_id} has no assignments to write"
        )

    creds = await oauth_service.load_credentials(db, user_id)
    loop = asyncio.get_running_loop()

    def _build_service() -> Any:
        return build("calendar", "v3", credentials=creds, cache_discovery=False)

    # 1. List existing app-marked events.
    try:
        existing = await loop.run_in_executor(
            None,
            lambda: _list_app_events_sync(
                _build_service(), target_calendar_id, snapshot_id=None
            ),
        )
    except HttpError as e:
        logger.warning("list app events failed: %s", e)
        raise CalendarApiError(str(e)) from e

    existing_ids = [ev["id"] for ev in existing]

    # 2. Delete (skipped on dry_run).
    if dry_run:
        deleted_count = len(existing_ids)
    else:
        try:
            deleted_count = await loop.run_in_executor(
                None,
                lambda: _delete_events_sync(
                    _build_service(), target_calendar_id, existing_ids
                ),
            )
        except HttpError as e:
            logger.warning("delete app events failed: %s", e)
            raise CalendarApiError(str(e)) from e
        await _clear_scheduled_event_ids_for_app_events(
            db, user_id, set(existing_ids)
        )

    # 3. Build bodies.
    bodies = [
        _build_event_body(
            task_id=task_id,
            task_title=task_title,
            snapshot_id=snapshot_id,
            fragment_index=idx,
            start=start,
            end=end,
        )
        for (task_id, task_title, idx, start, end) in planned
    ]

    # 4. Insert (skipped on dry_run).
    if dry_run:
        new_ids: list[str | None] = [None] * len(bodies)
    else:
        try:
            inserted = await loop.run_in_executor(
                None,
                lambda: _insert_events_sync(
                    _build_service(), target_calendar_id, bodies
                ),
            )
        except HttpError as e:
            logger.warning("insert app events failed: %s", e)
            raise CalendarApiError(str(e)) from e
        new_ids = list(inserted)

    # 5. Update tasks.scheduled_event_id (first fragment's event id).
    created_events: list[WrittenEvent] = []
    first_event_id_by_task: dict[str, str] = {}
    for (task_id, task_title, idx, start, end), event_id in zip(
        planned, new_ids, strict=True
    ):
        created_events.append(
            WrittenEvent(
                task_id=task_id,
                task_title=task_title,
                event_id=event_id,
                start=start,
                end=end,
                fragment_index=idx,
            )
        )
        if event_id is not None and idx == 0:
            first_event_id_by_task[task_id] = event_id

    if not dry_run:
        await _update_scheduled_event_ids(
            db, user_id, first_event_id_by_task=first_event_id_by_task
        )

    return WriteResult(
        snapshot_id=snapshot_id,
        dry_run=dry_run,
        deleted_event_count=deleted_count,
        created_events=created_events,
        target_calendar_id=target_calendar_id,
    )


async def delete_all_app_events(
    db: AsyncSession,
    user_id: str,
    *,
    target_calendar_id: str = "primary",
    snapshot_id: str | None = None,
) -> int:
    """Delete app-marked events. If snapshot_id is given, restrict to that snapshot."""
    creds = await oauth_service.load_credentials(db, user_id)
    loop = asyncio.get_running_loop()

    def _build_service() -> Any:
        return build("calendar", "v3", credentials=creds, cache_discovery=False)

    try:
        existing = await loop.run_in_executor(
            None,
            lambda: _list_app_events_sync(
                _build_service(), target_calendar_id, snapshot_id=snapshot_id
            ),
        )
    except HttpError as e:
        logger.warning("list app events failed: %s", e)
        raise CalendarApiError(str(e)) from e

    existing_ids = [ev["id"] for ev in existing]
    try:
        deleted = await loop.run_in_executor(
            None,
            lambda: _delete_events_sync(
                _build_service(), target_calendar_id, existing_ids
            ),
        )
    except HttpError as e:
        logger.warning("delete app events failed: %s", e)
        raise CalendarApiError(str(e)) from e

    await _clear_scheduled_event_ids_for_app_events(
        db, user_id, set(existing_ids)
    )
    return deleted
