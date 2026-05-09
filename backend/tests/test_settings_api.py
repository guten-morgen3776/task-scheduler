from httpx import AsyncClient


async def test_get_returns_defaults_on_first_call(client: AsyncClient) -> None:
    r = await client.get("/settings")
    assert r.status_code == 200
    data = r.json()
    assert data["work_hours"]["timezone"] == "Asia/Tokyo"
    assert data["slot_min_duration_min"] == 30
    assert data["slot_max_duration_min"] == 120
    # day_type_rules should be serialized with 'if' key (alias)
    assert "if" in data["day_type_rules"][0]
    assert "if_" not in data["day_type_rules"][0]


async def test_put_partial_update(client: AsyncClient) -> None:
    await client.get("/settings")  # ensure row exists
    r = await client.put(
        "/settings",
        json={
            "ignore_calendar_ids": ["ja.japanese#holiday@group.v.calendar.google.com"],
            "slot_max_duration_min": 90,
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ignore_calendar_ids"] == ["ja.japanese#holiday@group.v.calendar.google.com"]
    assert data["slot_max_duration_min"] == 90
    # untouched fields preserved
    assert data["slot_min_duration_min"] == 30


async def test_min_must_not_exceed_max(client: AsyncClient) -> None:
    r = await client.put(
        "/settings", json={"slot_min_duration_min": 200, "slot_max_duration_min": 100}
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "validation_error"


async def test_invalid_regex_rejected(client: AsyncClient) -> None:
    r = await client.put(
        "/settings",
        json={
            "calendar_location_rules": [
                {"event_summary_matches": "[unclosed", "location": "office"}
            ]
        },
    )
    assert r.status_code == 422


async def test_calendar_location_rule_requires_a_condition(client: AsyncClient) -> None:
    r = await client.put(
        "/settings",
        json={"calendar_location_rules": [{"location": "office"}]},
    )
    assert r.status_code == 422


async def test_reset_returns_defaults(client: AsyncClient) -> None:
    await client.put("/settings", json={"slot_max_duration_min": 90})
    r = await client.post("/settings/reset")
    assert r.status_code == 200
    assert r.json()["slot_max_duration_min"] == 120
