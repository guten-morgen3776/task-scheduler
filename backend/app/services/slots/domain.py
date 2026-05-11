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

    Event-based window (is_voluntary=False):
      - commute_to_min is recorded but the actual commute boundary is implied
        by the first event inside the window
      - events + linger zone (gaps free)
      - commute_from at end

    Voluntary visit window (is_voluntary=True): synthesized when the user has
    no events at this location that day but is willing to come there to work:
      - commute_to:  [start, start + commute_to_min)             busy
      - middle:      free at location (no event anchors)
      - commute_from: [end - commute_from_min, end)              busy

    Slots inside the free-at-location region inherit `location`. Slots outside
    any window default to "home".
    """

    location: Location
    start: datetime
    end: datetime
    commute_from_min: int = 0
    commute_to_min: int = 0
    is_voluntary: bool = False


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
