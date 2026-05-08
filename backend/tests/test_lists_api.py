from httpx import AsyncClient


async def test_create_and_list(client: AsyncClient) -> None:
    r = await client.post("/lists", json={"title": "勉強"})
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["title"] == "勉強"
    assert created["task_count"] == 0

    r = await client.get("/lists")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["id"] == created["id"]


async def test_update_and_delete(client: AsyncClient) -> None:
    r = await client.post("/lists", json={"title": "old"})
    list_id = r.json()["id"]

    r = await client.patch(f"/lists/{list_id}", json={"title": "new"})
    assert r.status_code == 200
    assert r.json()["title"] == "new"

    r = await client.delete(f"/lists/{list_id}")
    assert r.status_code == 204

    r = await client.get(f"/lists/{list_id}")
    assert r.status_code == 404


async def test_get_unknown_list(client: AsyncClient) -> None:
    r = await client.get("/lists/nonexistent")
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "not_found"


async def test_create_list_validation(client: AsyncClient) -> None:
    r = await client.post("/lists", json={"title": ""})
    assert r.status_code == 422
