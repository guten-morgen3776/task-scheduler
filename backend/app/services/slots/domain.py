from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel

from app.schemas.settings import Location


@dataclass(frozen=True)
class BusyPeriod:
    start: datetime
    end: datetime
    sources: tuple[str, ...]


@dataclass(frozen=True)
class LocationWindow:
    """Continuous span during a day where the user is at a single location.

    The window includes:
      - commute_to:    [start, start + commute_to_min)             busy
      - events + linger zone:                                       events busy, gaps free
      - commute_from:  [end - commute_from_min, end)                busy

    Slots that fall entirely inside the linger/event-gap region inherit
    `location`. Slots outside any window default to "home".
    """

    location: Location
    start: datetime
    end: datetime
    commute_from_min: int = 0


@dataclass(frozen=True)
class DayTypeResult:
    name: str
    energy: float
    allowed_max_task_duration_min: int


class Slot(BaseModel):
    id: str
    start: datetime
    duration_min: int
    energy_score: float
    allowed_max_task_duration_min: int
    day_type: str
    location: Location


def make_slot_id(start_utc: datetime, duration_min: int) -> str:
    return f"slot-{start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}-{duration_min}"
