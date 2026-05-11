from httpx import AsyncClient


async def _make_list(client: AsyncClient, title: str = "list") -> str:
    r = await client.post("/lists", json={"title": title})
    return r.json()["id"]


async def test_full_crud_flow(client: AsyncClient) -> None:
    list_id = await _make_list(client)

    r = await client.post(
        f"/lists/{list_id}/tasks",
        json={
            "title": "レポート執筆",
            "duration_min": 90,
            "priority": 4,
            "deadline": "2026-05-15T23:59:59+09:00",
        },
    )
    assert r.status_code == 201, r.text
    task = r.json()
    assert task["title"] == "レポート執筆"
    assert task["duration_min"] == 90
    assert task["priority"] == 4
    assert task["completed"] is False
    assert task["scheduled_end"] is None
    task_id = task["id"]

    r = await client.get(f"/lists/{list_id}/tasks")
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = await client.get(f"/tasks/{task_id}")
    assert r.status_code == 200
    assert r.json()["subtasks"] == []

    r = await client.patch(f"/tasks/{task_id}", json={"title": "改題", "duration_min": 60})
    assert r.status_code == 200
    assert r.json()["title"] == "改題"
    assert r.json()["duration_min"] == 60

    r = await client.post(f"/tasks/{task_id}/complete")
    assert r.status_code == 200
    assert r.json()["completed"] is True
    assert r.json()["completed_at"] is not None

    r = await client.get(f"/lists/{list_id}/tasks")
    assert r.json() == []

    r = await client.get(f"/lists/{list_id}/tasks?include_completed=true")
    assert len(r.json()) == 1

    r = await client.post(f"/tasks/{task_id}/uncomplete")
    assert r.status_code == 200
    assert r.json()["completed"] is False

    r = await client.delete(f"/tasks/{task_id}")
    assert r.status_code == 204

    r = await client.get(f"/tasks/{task_id}")
    assert r.status_code == 404


async def test_defaults_applied_when_unspecified(client: AsyncClient) -> None:
    list_id = await _make_list(client)
    r = await client.post(f"/lists/{list_id}/tasks", json={"title": "簡素"})
    assert r.status_code == 201
    task = r.json()
    assert task["duration_min"] == 60
    assert task["priority"] == 3


async def test_invalid_priority_rejected(client: AsyncClient) -> None:
    list_id = await _make_list(client)
    r = await client.post(
        f"/lists/{list_id}/tasks", json={"title": "x", "priority": 99}
    )
    assert r.status_code == 422


async def test_invalid_duration_rejected(client: AsyncClient) -> None:
    list_id = await _make_list(client)
    r = await client.post(
        f"/lists/{list_id}/tasks", json={"title": "x", "duration_min": 0}
    )
    assert r.status_code == 422


async def test_subtask_basics(client: AsyncClient) -> None:
    list_id = await _make_list(client)
    parent = (await client.post(f"/lists/{list_id}/tasks", json={"title": "親"})).json()
    child = (
        await client.post(
            f"/lists/{list_id}/tasks", json={"title": "子", "parent_id": parent["id"]}
        )
    ).json()

    r = await client.get(f"/tasks/{parent['id']}")
    assert r.status_code == 200
    subs = r.json()["subtasks"]
    assert len(subs) == 1
    assert subs[0]["id"] == child["id"]


async def test_subtask_nested_rejected(client: AsyncClient) -> None:
    list_id = await _make_list(client)
    parent = (await client.post(f"/lists/{list_id}/tasks", json={"title": "親"})).json()
    child = (
        await client.post(
            f"/lists/{list_id}/tasks", json={"title": "子", "parent_id": parent["id"]}
        )
    ).json()
    r = await client.post(
        f"/lists/{list_id}/tasks", json={"title": "孫", "parent_id": child["id"]}
    )
    assert r.status_code == 400
    assert "nested" in r.json()["detail"]["message"].lower()


async def test_move_task_between_lists(client: AsyncClient) -> None:
    list_a = await _make_list(client, "A")
    list_b = await _make_list(client, "B")
    task = (await client.post(f"/lists/{list_a}/tasks", json={"title": "x"})).json()

    r = await client.post(f"/tasks/{task['id']}/move", json={"list_id": list_b})
    assert r.status_code == 200
    assert r.json()["list_id"] == list_b

    assert (await client.get(f"/lists/{list_a}/tasks")).json() == []
    assert len((await client.get(f"/lists/{list_b}/tasks")).json()) == 1


async def test_list_count_aggregation(client: AsyncClient) -> None:
    list_id = await _make_list(client)
    t1 = (await client.post(f"/lists/{list_id}/tasks", json={"title": "a"})).json()
    await client.post(f"/lists/{list_id}/tasks", json={"title": "b"})
    await client.post(f"/tasks/{t1['id']}/complete")

    r = await client.get("/lists")
    counts = r.json()[0]
    assert counts["task_count"] == 2
    assert counts["completed_count"] == 1


async def test_list_scheduled_tasks(client: AsyncClient, db_session, test_user) -> None:
    """tasks.scheduled_start で絞り込みできることを確認。"""
    from datetime import UTC, datetime
    from app.models import Task, TaskList

    list_row = TaskList(user_id=test_user.id, title="x", position="000010")
    db_session.add(list_row)
    await db_session.flush()

    placed_in_range = Task(
        user_id=test_user.id,
        list_id=list_row.id,
        title="A",
        position="000010",
        duration_min=60,
        scheduled_start=datetime(2026, 5, 12, 3, 0, tzinfo=UTC),
        scheduled_end=datetime(2026, 5, 12, 4, 0, tzinfo=UTC),
    )
    placed_outside = Task(
        user_id=test_user.id,
        list_id=list_row.id,
        title="B",
        position="000020",
        duration_min=60,
        scheduled_start=datetime(2026, 6, 1, 3, 0, tzinfo=UTC),
        scheduled_end=datetime(2026, 6, 1, 4, 0, tzinfo=UTC),
    )
    unplaced = Task(
        user_id=test_user.id,
        list_id=list_row.id,
        title="C",
        position="000030",
        duration_min=60,
    )
    db_session.add_all([placed_in_range, placed_outside, unplaced])
    await db_session.commit()

    r = await client.get(
        "/tasks/scheduled?start=2026-05-10T00:00:00%2B00:00&end=2026-05-15T00:00:00%2B00:00"
    )
    assert r.status_code == 200, r.text
    titles = [t["title"] for t in r.json()]
    assert titles == ["A"]

    # No range = everything with a placement.
    r = await client.get("/tasks/scheduled")
    titles = [t["title"] for t in r.json()]
    assert set(titles) == {"A", "B"}


async def test_scheduled_endpoint_rejects_naive_datetime(client: AsyncClient) -> None:
    r = await client.get("/tasks/scheduled?start=2026-05-10T00:00:00")
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "validation_error"


async def test_sync_from_calendar_updates_db(
    client: AsyncClient, db_session, test_user
) -> None:
    """app マーカー付き events を読んで tasks.scheduled_* を埋める。"""
    from datetime import UTC, datetime
    from unittest.mock import MagicMock, patch
    from app.models import Task, TaskList
    from app.services.optimizer import writer as optimizer_writer
    from app.services.tasks import tasks as tasks_service

    list_row = TaskList(user_id=test_user.id, title="x", position="000010")
    db_session.add(list_row)
    await db_session.flush()
    list_id = list_row.id

    a = Task(
        user_id=test_user.id,
        list_id=list_id,
        title="A",
        position="000010",
        duration_min=60,
        # No scheduled_* yet — should be filled by sync.
    )
    stale = Task(
        user_id=test_user.id,
        list_id=list_id,
        title="stale",
        position="000020",
        duration_min=60,
        scheduled_event_id="ghost_event",
        scheduled_start=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
        scheduled_end=datetime(2026, 5, 1, 1, 0, tzinfo=UTC),
    )
    db_session.add_all([a, stale])
    await db_session.commit()

    fake_events = [
        {
            "id": "ev_001",
            "start": {"dateTime": "2026-05-12T03:00:00+00:00"},
            "end": {"dateTime": "2026-05-12T04:00:00+00:00"},
            "extendedProperties": {
                "private": {
                    "task_scheduler": "1",
                    "task_id": a.id,
                    "fragment_index": "0",
                }
            },
        },
    ]

    with (
        patch.object(optimizer_writer.oauth_service, "load_credentials") as load_creds,
        patch.object(optimizer_writer, "_list_app_events_sync", return_value=fake_events),
        patch("app.api.tasks.build", create=True),
    ):
        load_creds.return_value = MagicMock()
        # Patch oauth_service in tasks API context too
        with patch("app.api.tasks.oauth_service.load_credentials", return_value=MagicMock()):
            r = await client.post("/tasks/sync-from-calendar")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated_task_count"] == 1
    assert body["cleared_task_count"] == 1
    assert body["event_count"] == 1

    # Pull fresh state via service (avoids stale ORM cache concerns).
    rows = await tasks_service.list_scheduled_tasks(db_session, test_user.id)
    titles_with_placement = {t.title for t in rows}
    assert titles_with_placement == {"A"}
    fresh_a = next(t for t in rows if t.title == "A")
    assert fresh_a.scheduled_event_id == "ev_001"
    assert fresh_a.scheduled_start == datetime(2026, 5, 12, 3, 0, tzinfo=UTC)


async def test_apply_populates_scheduled_fragments(
    client: AsyncClient, db_session, test_user
) -> None:
    """apply は複数 fragments をそのまま scheduled_fragments に保存する。"""
    from datetime import UTC, datetime, timedelta
    from app.models import OptimizerSnapshot, Task, TaskList

    list_row = TaskList(user_id=test_user.id, title="x", position="000010")
    db_session.add(list_row)
    await db_session.flush()

    task = Task(
        user_id=test_user.id,
        list_id=list_row.id,
        title="multi",
        position="000010",
        duration_min=120,
    )
    db_session.add(task)
    await db_session.flush()

    f1_start = datetime(2026, 5, 10, 11, 0, tzinfo=UTC)
    f2_start = datetime(2026, 5, 10, 17, 0, tzinfo=UTC)
    snap = OptimizerSnapshot(
        user_id=test_user.id,
        tasks_json=[{"id": task.id, "title": "multi"}],
        slots_json=[],
        config_json={},
        result_json={
            "status": "optimal",
            "objective_value": 0.0,
            "assignments": [
                {
                    "task_id": task.id,
                    "fragments": [
                        {"slot_id": "s1", "start": f1_start.isoformat(), "duration_min": 60},
                        {"slot_id": "s2", "start": f2_start.isoformat(), "duration_min": 120},
                    ],
                    "total_assigned_min": 180,
                }
            ],
            "unassigned_task_ids": [],
            "solve_time_sec": 0.0,
            "notes": [],
        },
    )
    db_session.add(snap)
    await db_session.commit()

    r = await client.post(f"/optimizer/snapshots/{snap.id}/apply")
    assert r.status_code == 200, r.text
    assert r.json()["updated_task_count"] == 1

    r = await client.get(f"/tasks/{task.id}")
    body = r.json()
    frags = body["scheduled_fragments"]
    assert frags is not None
    assert len(frags) == 2
    # Sorted by start, with end derived from duration_min.
    assert datetime.fromisoformat(frags[0]["start"]) == f1_start
    assert (
        datetime.fromisoformat(frags[0]["end"])
        == f1_start + timedelta(minutes=60)
    )
    assert datetime.fromisoformat(frags[1]["start"]) == f2_start
    assert (
        datetime.fromisoformat(frags[1]["end"])
        == f2_start + timedelta(minutes=120)
    )
    # scheduled_start / end span the whole.
    assert datetime.fromisoformat(body["scheduled_start"]) == f1_start
    assert (
        datetime.fromisoformat(body["scheduled_end"])
        == f2_start + timedelta(minutes=120)
    )


async def test_sync_from_calendar_populates_fragments(
    client: AsyncClient, db_session, test_user
) -> None:
    """同期も複数 events を fragments としてまとめて保存する。"""
    from datetime import UTC, datetime
    from unittest.mock import MagicMock, patch
    from app.models import Task, TaskList
    from app.services.optimizer import writer as optimizer_writer
    from app.services.tasks import tasks as tasks_service

    list_row = TaskList(user_id=test_user.id, title="x", position="000010")
    db_session.add(list_row)
    await db_session.flush()

    task = Task(
        user_id=test_user.id,
        list_id=list_row.id,
        title="A",
        position="000010",
        duration_min=120,
    )
    db_session.add(task)
    await db_session.commit()

    fake_events = [
        {
            "id": "ev_001",
            "start": {"dateTime": "2026-05-10T11:00:00+00:00"},
            "end": {"dateTime": "2026-05-10T12:00:00+00:00"},
            "extendedProperties": {
                "private": {
                    "task_scheduler": "1",
                    "task_id": task.id,
                    "fragment_index": "0",
                }
            },
        },
        {
            "id": "ev_002",
            "start": {"dateTime": "2026-05-10T17:00:00+00:00"},
            "end": {"dateTime": "2026-05-10T19:00:00+00:00"},
            "extendedProperties": {
                "private": {
                    "task_scheduler": "1",
                    "task_id": task.id,
                    "fragment_index": "1",
                }
            },
        },
    ]

    with (
        patch.object(optimizer_writer.oauth_service, "load_credentials") as load_creds,
        patch.object(optimizer_writer, "_list_app_events_sync", return_value=fake_events),
        patch("app.api.tasks.build", create=True),
    ):
        load_creds.return_value = MagicMock()
        with patch("app.api.tasks.oauth_service.load_credentials", return_value=MagicMock()):
            r = await client.post("/tasks/sync-from-calendar")

    assert r.status_code == 200, r.text
    rows = await tasks_service.list_scheduled_tasks(db_session, test_user.id)
    assert len(rows) == 1
    fresh = rows[0]
    assert fresh.scheduled_fragments is not None
    assert len(fresh.scheduled_fragments) == 2
    # Ordered chronologically.
    assert datetime.fromisoformat(fresh.scheduled_fragments[0]["start"]) == datetime(
        2026, 5, 10, 11, 0, tzinfo=UTC
    )
    assert datetime.fromisoformat(fresh.scheduled_fragments[1]["start"]) == datetime(
        2026, 5, 10, 17, 0, tzinfo=UTC
    )
    # scheduled_event_id is the fragment_index=0 event.
    assert fresh.scheduled_event_id == "ev_001"


async def test_scheduled_fixed_can_be_patched(client: AsyncClient) -> None:
    list_id = (await client.post("/lists", json={"title": "x"})).json()["id"]
    task = (
        await client.post(
            f"/lists/{list_id}/tasks", json={"title": "t", "duration_min": 60}
        )
    ).json()
    assert task["scheduled_fixed"] is False

    r = await client.patch(f"/tasks/{task['id']}", json={"scheduled_fixed": True})
    assert r.status_code == 200
    assert r.json()["scheduled_fixed"] is True

    r = await client.patch(f"/tasks/{task['id']}", json={"scheduled_fixed": False})
    assert r.json()["scheduled_fixed"] is False


async def test_scheduled_endpoint_excludes_completed_by_default(
    client: AsyncClient, db_session, test_user
) -> None:
    """GET /tasks/scheduled omits completed tasks by default; include_completed=true brings them back."""
    from datetime import UTC, datetime
    from app.models import Task, TaskList

    list_row = TaskList(user_id=test_user.id, title="x", position="000010")
    db_session.add(list_row)
    await db_session.flush()

    active = Task(
        user_id=test_user.id,
        list_id=list_row.id,
        title="active",
        position="000010",
        duration_min=60,
        scheduled_start=datetime(2026, 5, 12, 3, 0, tzinfo=UTC),
        scheduled_end=datetime(2026, 5, 12, 4, 0, tzinfo=UTC),
        completed=False,
    )
    done = Task(
        user_id=test_user.id,
        list_id=list_row.id,
        title="done",
        position="000020",
        duration_min=60,
        scheduled_start=datetime(2026, 5, 12, 5, 0, tzinfo=UTC),
        scheduled_end=datetime(2026, 5, 12, 6, 0, tzinfo=UTC),
        completed=True,
        completed_at=datetime(2026, 5, 12, 6, 0, tzinfo=UTC),
    )
    db_session.add_all([active, done])
    await db_session.commit()

    # Default: completed excluded.
    r = await client.get("/tasks/scheduled")
    titles = [t["title"] for t in r.json()]
    assert titles == ["active"]

    # Opt-in: both returned.
    r = await client.get("/tasks/scheduled?include_completed=true")
    titles = sorted(t["title"] for t in r.json())
    assert titles == ["active", "done"]


async def test_event_log_records_task_lifecycle(
    client: AsyncClient, db_session, test_user
) -> None:
    """Sanity: creating + completing a task writes corresponding event_log rows."""
    from sqlalchemy import select
    from app.models import EventLog

    list_id = (await client.post("/lists", json={"title": "x"})).json()["id"]
    task = (
        await client.post(
            f"/lists/{list_id}/tasks",
            json={"title": "log-target", "duration_min": 60},
        )
    ).json()
    await client.post(f"/tasks/{task['id']}/complete")

    rows = (
        await db_session.execute(
            select(EventLog)
            .where(EventLog.user_id == test_user.id, EventLog.subject_id == task["id"])
            .order_by(EventLog.id)
        )
    ).scalars().all()
    types = [r.event_type for r in rows]
    assert "task.created" in types
    assert "task.completed" in types
    completed = next(r for r in rows if r.event_type == "task.completed")
    # Payload carries the values useful for accuracy analysis later.
    assert completed.payload["duration_min"] == 60
    assert "completed_at" in completed.payload
