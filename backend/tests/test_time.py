from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.core.time import ensure_aware, to_app_tz, to_utc, utc_now


def test_utc_now_is_aware_and_utc() -> None:
    now = utc_now()
    assert now.tzinfo is not None
    assert now.utcoffset().total_seconds() == 0


def test_to_app_tz_converts_to_jst() -> None:
    dt = datetime(2026, 5, 8, 12, 0, tzinfo=UTC)
    converted = to_app_tz(dt)
    assert converted.tzinfo == ZoneInfo("Asia/Tokyo")
    assert converted.hour == 21


def test_to_utc_roundtrip() -> None:
    jst = datetime(2026, 5, 8, 21, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    utc = to_utc(jst)
    assert utc.tzinfo == UTC
    assert utc.hour == 12


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValueError):
        to_utc(datetime(2026, 5, 8, 12, 0))
    with pytest.raises(ValueError):
        ensure_aware(datetime(2026, 5, 8, 12, 0))
