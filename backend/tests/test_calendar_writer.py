"""Phase 5 calendar-writer tests.

Mocks both Google API client and OAuth credential loading so the tests
don't hit real Google services.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OptimizerSnapshot, Task, TaskList, User
from app.services.optimizer import writer


@pytest_asyncio.fixture
async def task_list(db_session: AsyncSession, test_user: User) -> TaskList:
    row = TaskList(user_id=test_user.id, title="x", position="000010")
    db_session.add(row)
    await db_session.flush()
    return row


@pytest_asyncio.fixture
async def task_a(
    db_session: AsyncSession, test_user: User, task_list: TaskList
) -> Task:
    t = Task(
        user_id=test_user.id,
        list_id=task_list.id,
        title="レポート執筆",
        position="000010",
        duration_min=120,
    )
    db_session.add(t)
    await db_session.flush()
    return t


@pytest_asyncio.fixture
async def task_b(
    db_session: AsyncSession, test_user: User, task_list: TaskList
) -> Task:
    t = Task(
        user_id=test_user.id,
        list_id=task_list.id,
        title="読書",
        position="000020",
        duration_min=60,
    )
    db_session.add(t)
    await db_session.flush()
    return t


def _snapshot_for(
    user_id: str,
    *,
    fragments_by_task: dict[str, list[tuple[datetime, int]]],
    titles: dict[str, str],
) -> OptimizerSnapshot:
    """Build a minimal but valid OptimizerSnapshot fixture."""
    tasks_json = [
        {
            "id": tid,
            "title": titles[tid],
            "duration_min": sum(d for _, d in frags),
            "deadline": None,
            "priority": 3,
            "location": None,
        }
        for tid, frags in fragments_by_task.items()
    ]
    assignments = [
        {
            "task_id": tid,
            "fragments": [
                {
                    "task_id": tid,
                    "slot_id": f"slot{i}",
                    "start": s.isoformat(),
                    "duration_min": d,
                }
                for i, (s, d) in enumerate(frags)
            ],
            "total_assigned_min": sum(d for _, d in frags),
        }
        for tid, frags in fragments_by_task.items()
    ]
    return OptimizerSnapshot(
        user_id=user_id,
        tasks_json=tasks_json,
        slots_json=[],
        config_json={},
        result_json={
            "status": "optimal",
            "objective_value": 0.0,
            "assignments": assignments,
            "unassigned_task_ids": [],
            "solve_time_sec": 0.0,
            "notes": [],
        },
        note=None,
    )


@pytest.fixture
def mock_creds():
    with patch.object(
        writer.oauth_service, "load_credentials"
    ) as load_creds:
        load_creds.return_value = MagicMock(name="creds")
        yield load_creds


@pytest.fixture
def fake_calendar_service():
    """Returns a stand-in `service` whose events().list/delete/insert can be inspected.

    Pre-configure `existing_events` and `inserted_event_ids` on the returned
    helper to control the mock's behavior per-test.
    """

    class FakeCalendar:
        def __init__(self) -> None:
            self.existing_events: list[dict] = []
            self.inserted_event_ids: list[str] = []
            self.list_calls: list[dict] = []
            self.delete_calls: list[str] = []
            self.insert_calls: list[dict] = []

        def build_service(self) -> MagicMock:
            service = MagicMock(name="calendar_service")

            def list_(**kwargs):
                self.list_calls.append(kwargs)
                exec_ = MagicMock()
                # Filter `existing_events` by the privateExtendedProperty filters
                # to mimic real API behavior for snapshot-scoped listing.
                pep = kwargs.get("privateExtendedProperty") or []
                filters = [p.split("=", 1) for p in pep]
                filtered = []
                for ev in self.existing_events:
                    private = (ev.get("extendedProperties") or {}).get(
                        "private"
                    ) or {}
                    if all(private.get(k) == v for k, v in filters):
                        filtered.append(ev)
                exec_.execute.return_value = {"items": filtered, "nextPageToken": None}
                return exec_

            def delete_(calendarId: str, eventId: str):
                self.delete_calls.append(eventId)
                exec_ = MagicMock()
                exec_.execute.return_value = None
                return exec_

            def insert_(calendarId: str, body: dict):
                self.insert_calls.append(body)
                fake_id = f"ev_{len(self.insert_calls):03d}"
                self.inserted_event_ids.append(fake_id)
                exec_ = MagicMock()
                exec_.execute.return_value = {"id": fake_id}
                return exec_

            events_obj = MagicMock()
            events_obj.list = MagicMock(side_effect=list_)
            events_obj.delete = MagicMock(side_effect=delete_)
            events_obj.insert = MagicMock(side_effect=insert_)
            service.events.return_value = events_obj
            return service

    fake = FakeCalendar()
    with patch.object(writer, "build") as build_mock:
        build_mock.side_effect = lambda *a, **kw: fake.build_service()
        yield fake


# ─────────────────────────────────────────────────────────────────────
# write_snapshot
# ─────────────────────────────────────────────────────────────────────


async def test_write_creates_events_with_marker(
    db_session: AsyncSession,
    test_user: User,
    task_a: Task,
    mock_creds,
    fake_calendar_service,
) -> None:
    snap = _snapshot_for(
        test_user.id,
        fragments_by_task={
            task_a.id: [(datetime(2026, 5, 12, 3, 0, tzinfo=UTC), 60)],
        },
        titles={task_a.id: task_a.title},
    )
    db_session.add(snap)
    await db_session.flush()

    result = await writer.write_snapshot(
        db_session, test_user.id, snap.id, dry_run=False
    )

    assert result.dry_run is False
    assert result.deleted_event_count == 0
    assert len(result.created_events) == 1
    body = fake_calendar_service.insert_calls[0]
    assert body["summary"].startswith("[task-scheduler]")
    assert body["summary"].endswith("レポート執筆")
    private = body["extendedProperties"]["private"]
    assert private["task_scheduler"] == "1"
    assert private["snapshot_id"] == snap.id
    assert private["task_id"] == task_a.id
    assert private["fragment_index"] == "0"
    # Reminders silenced.
    assert body["reminders"] == {"useDefault": False, "overrides": []}


async def test_dry_run_skips_delete_and_insert(
    db_session: AsyncSession,
    test_user: User,
    task_a: Task,
    mock_creds,
    fake_calendar_service,
) -> None:
    snap = _snapshot_for(
        test_user.id,
        fragments_by_task={
            task_a.id: [(datetime(2026, 5, 12, 3, 0, tzinfo=UTC), 60)],
        },
        titles={task_a.id: task_a.title},
    )
    db_session.add(snap)
    await db_session.flush()

    # Pretend two events already exist.
    fake_calendar_service.existing_events = [
        {
            "id": "old_a",
            "extendedProperties": {"private": {"task_scheduler": "1"}},
        },
        {
            "id": "old_b",
            "extendedProperties": {"private": {"task_scheduler": "1"}},
        },
    ]

    result = await writer.write_snapshot(
        db_session, test_user.id, snap.id, dry_run=True
    )

    assert result.dry_run is True
    assert result.deleted_event_count == 2  # would delete
    assert len(result.created_events) == 1
    assert result.created_events[0].event_id is None
    assert fake_calendar_service.delete_calls == []
    assert fake_calendar_service.insert_calls == []


async def test_re_write_deletes_existing_then_inserts(
    db_session: AsyncSession,
    test_user: User,
    task_a: Task,
    task_b: Task,
    mock_creds,
    fake_calendar_service,
) -> None:
    snap = _snapshot_for(
        test_user.id,
        fragments_by_task={
            task_a.id: [(datetime(2026, 5, 12, 3, 0, tzinfo=UTC), 60)],
            task_b.id: [(datetime(2026, 5, 12, 5, 0, tzinfo=UTC), 30)],
        },
        titles={task_a.id: task_a.title, task_b.id: task_b.title},
    )
    db_session.add(snap)
    await db_session.flush()

    fake_calendar_service.existing_events = [
        {
            "id": f"old_{i}",
            "extendedProperties": {"private": {"task_scheduler": "1"}},
        }
        for i in range(3)
    ]

    result = await writer.write_snapshot(
        db_session, test_user.id, snap.id, dry_run=False
    )

    assert result.deleted_event_count == 3
    assert sorted(fake_calendar_service.delete_calls) == [
        "old_0",
        "old_1",
        "old_2",
    ]
    assert len(fake_calendar_service.insert_calls) == 2


async def test_scheduled_event_id_updated_for_first_fragment(
    db_session: AsyncSession,
    test_user: User,
    task_a: Task,
    mock_creds,
    fake_calendar_service,
) -> None:
    """Multi-fragment task: scheduled_event_id stores the first fragment's id."""
    snap = _snapshot_for(
        test_user.id,
        fragments_by_task={
            task_a.id: [
                (datetime(2026, 5, 12, 3, 0, tzinfo=UTC), 60),
                (datetime(2026, 5, 12, 5, 0, tzinfo=UTC), 60),
            ],
        },
        titles={task_a.id: task_a.title},
    )
    db_session.add(snap)
    await db_session.flush()

    await writer.write_snapshot(
        db_session, test_user.id, snap.id, dry_run=False
    )

    await db_session.refresh(task_a)
    assert task_a.scheduled_event_id == "ev_001"


async def test_dry_run_does_not_touch_scheduled_event_id(
    db_session: AsyncSession,
    test_user: User,
    task_a: Task,
    mock_creds,
    fake_calendar_service,
) -> None:
    task_a.scheduled_event_id = None
    await db_session.flush()
    snap = _snapshot_for(
        test_user.id,
        fragments_by_task={
            task_a.id: [(datetime(2026, 5, 12, 3, 0, tzinfo=UTC), 60)],
        },
        titles={task_a.id: task_a.title},
    )
    db_session.add(snap)
    await db_session.flush()

    await writer.write_snapshot(
        db_session, test_user.id, snap.id, dry_run=True
    )

    await db_session.refresh(task_a)
    assert task_a.scheduled_event_id is None


async def test_nothing_to_write_when_no_assignments(
    db_session: AsyncSession,
    test_user: User,
    mock_creds,
    fake_calendar_service,
) -> None:
    snap = OptimizerSnapshot(
        user_id=test_user.id,
        tasks_json=[],
        slots_json=[],
        config_json={},
        result_json={
            "status": "infeasible",
            "objective_value": None,
            "assignments": [],
            "unassigned_task_ids": [],
            "solve_time_sec": 0.0,
            "notes": [],
        },
        note=None,
    )
    db_session.add(snap)
    await db_session.flush()

    with pytest.raises(writer.NothingToWriteError):
        await writer.write_snapshot(
            db_session, test_user.id, snap.id, dry_run=False
        )


async def test_snapshot_not_found(
    db_session: AsyncSession, test_user: User, mock_creds
) -> None:
    with pytest.raises(writer.SnapshotNotFoundError):
        await writer.write_snapshot(
            db_session, test_user.id, "00000000000000000000000000000000"
        )


# ─────────────────────────────────────────────────────────────────────
# delete_all_app_events
# ─────────────────────────────────────────────────────────────────────


async def test_delete_all_app_events(
    db_session: AsyncSession,
    test_user: User,
    task_a: Task,
    mock_creds,
    fake_calendar_service,
) -> None:
    task_a.scheduled_event_id = "old_1"
    await db_session.flush()

    fake_calendar_service.existing_events = [
        {
            "id": f"old_{i}",
            "extendedProperties": {"private": {"task_scheduler": "1"}},
        }
        for i in range(3)
    ]

    deleted = await writer.delete_all_app_events(db_session, test_user.id)
    assert deleted == 3
    assert sorted(fake_calendar_service.delete_calls) == [
        "old_0",
        "old_1",
        "old_2",
    ]
    await db_session.refresh(task_a)
    assert task_a.scheduled_event_id is None


async def test_delete_only_for_specific_snapshot(
    db_session: AsyncSession,
    test_user: User,
    mock_creds,
    fake_calendar_service,
) -> None:
    fake_calendar_service.existing_events = [
        {
            "id": "old_a",
            "extendedProperties": {
                "private": {"task_scheduler": "1", "snapshot_id": "snapA"}
            },
        },
        {
            "id": "old_b",
            "extendedProperties": {
                "private": {"task_scheduler": "1", "snapshot_id": "snapB"}
            },
        },
    ]

    deleted = await writer.delete_all_app_events(
        db_session, test_user.id, snapshot_id="snapA"
    )
    assert deleted == 1
    assert fake_calendar_service.delete_calls == ["old_a"]


# ─────────────────────────────────────────────────────────────────────
# API endpoints
# ─────────────────────────────────────────────────────────────────────


async def test_write_endpoint_round_trip(
    client,
    db_session: AsyncSession,
    test_user: User,
    task_a: Task,
    mock_creds,
    fake_calendar_service,
) -> None:
    snap = _snapshot_for(
        test_user.id,
        fragments_by_task={
            task_a.id: [(datetime(2026, 5, 12, 3, 0, tzinfo=UTC), 60)],
        },
        titles={task_a.id: task_a.title},
    )
    db_session.add(snap)
    await db_session.commit()

    r = await client.post(
        f"/optimizer/snapshots/{snap.id}/write",
        json={"dry_run": False},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is False
    assert body["snapshot_id"] == snap.id
    assert len(body["created_events"]) == 1
    assert body["created_events"][0]["event_id"] == "ev_001"


async def test_write_endpoint_dry_run(
    client,
    db_session: AsyncSession,
    test_user: User,
    task_a: Task,
    mock_creds,
    fake_calendar_service,
) -> None:
    snap = _snapshot_for(
        test_user.id,
        fragments_by_task={
            task_a.id: [(datetime(2026, 5, 12, 3, 0, tzinfo=UTC), 60)],
        },
        titles={task_a.id: task_a.title},
    )
    db_session.add(snap)
    await db_session.commit()

    r = await client.post(
        f"/optimizer/snapshots/{snap.id}/write",
        json={"dry_run": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True
    assert body["created_events"][0]["event_id"] is None
    assert fake_calendar_service.insert_calls == []


async def test_write_endpoint_404_for_unknown_snapshot(
    client, mock_creds, fake_calendar_service
) -> None:
    r = await client.post(
        "/optimizer/snapshots/00000000000000000000000000000000/write",
        json={"dry_run": True},
    )
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "not_found"


async def test_delete_write_endpoint(
    client,
    db_session: AsyncSession,
    test_user: User,
    mock_creds,
    fake_calendar_service,
) -> None:
    fake_calendar_service.existing_events = [
        {
            "id": "old_a",
            "extendedProperties": {"private": {"task_scheduler": "1"}},
        },
    ]

    # snapshot_id is required by the route but ignored when only_this_snapshot=false.
    r = await client.delete("/optimizer/snapshots/anything/write")
    assert r.status_code == 200
    assert r.json()["deleted_event_count"] == 1
    assert fake_calendar_service.delete_calls == ["old_a"]
