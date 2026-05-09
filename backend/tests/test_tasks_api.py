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
