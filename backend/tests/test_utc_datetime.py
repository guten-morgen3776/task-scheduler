from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import StatementError

from app.models import Task, TaskList, User


async def test_jst_input_round_trips_with_tz(client: AsyncClient) -> None:
    list_id = (await client.post("/lists", json={"title": "x"})).json()["id"]

    deadline_iso = "2026-05-15T23:59:59+09:00"
    create = await client.post(
        f"/lists/{list_id}/tasks",
        json={"title": "t", "deadline": deadline_iso},
    )
    assert create.status_code == 201

    rows = (await client.get(f"/lists/{list_id}/tasks")).json()
    assert len(rows) == 1
    fetched = rows[0]

    assert fetched["deadline"] is not None
    parsed = datetime.fromisoformat(fetched["deadline"])
    assert parsed.tzinfo is not None, "deadline lost its timezone on read"
    assert parsed == datetime(2026, 5, 15, 23, 59, 59, tzinfo=ZoneInfo("Asia/Tokyo"))


async def test_created_at_has_tz_after_read(client: AsyncClient) -> None:
    create = await client.post("/lists", json={"title": "x"})
    list_id = create.json()["id"]

    rows = (await client.get("/lists")).json()
    target = next(r for r in rows if r["id"] == list_id)
    parsed = datetime.fromisoformat(target["created_at"])
    assert parsed.tzinfo is not None, "created_at lost its timezone on read"
    assert parsed.utcoffset().total_seconds() == 0


async def test_naive_datetime_rejected_at_db(db_session, test_user: User) -> None:
    list_row = TaskList(user_id=test_user.id, title="x", position="000010")
    db_session.add(list_row)
    await db_session.flush()
    list_id = list_row.id

    task = Task(
        user_id=test_user.id,
        list_id=list_id,
        title="t",
        position="000010",
        deadline=datetime(2026, 5, 15, 23, 59, 59),
    )
    db_session.add(task)
    with pytest.raises(StatementError) as exc_info:
        await db_session.flush()
    assert isinstance(exc_info.value.orig, ValueError)
    await db_session.rollback()


async def test_utc_input_round_trips(client: AsyncClient) -> None:
    list_id = (await client.post("/lists", json={"title": "x"})).json()["id"]
    deadline_iso = "2026-05-15T14:59:59+00:00"
    await client.post(f"/lists/{list_id}/tasks", json={"title": "t", "deadline": deadline_iso})
    rows = (await client.get(f"/lists/{list_id}/tasks")).json()
    parsed = datetime.fromisoformat(rows[0]["deadline"])
    assert parsed == datetime(2026, 5, 15, 14, 59, 59, tzinfo=UTC)
