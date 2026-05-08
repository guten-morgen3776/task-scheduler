from httpx import AsyncClient


async def test_naive_start_rejected(client: AsyncClient) -> None:
    r = await client.get("/calendar/events?start=2026-05-08T00:00:00&end=2026-05-09T00:00:00%2B09:00")
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "validation_error"


async def test_end_before_start_rejected(client: AsyncClient) -> None:
    r = await client.get(
        "/calendar/events?start=2026-05-09T00:00:00%2B09:00&end=2026-05-08T00:00:00%2B09:00"
    )
    assert r.status_code == 400


async def test_empty_calendar_ids_rejected(client: AsyncClient) -> None:
    r = await client.get(
        "/calendar/events"
        "?start=2026-05-08T00:00:00%2B09:00"
        "&end=2026-05-09T00:00:00%2B09:00"
        "&calendar_ids=,,,"
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "validation_error"
