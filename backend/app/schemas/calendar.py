from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class CalendarEvent(BaseModel):
    id: str
    calendar_id: str
    summary: str
    description: str | None
    start: datetime
    end: datetime
    all_day: bool
    location: str | None
    status: Literal["confirmed", "tentative", "cancelled"]
    source: Literal["google"] = "google"
    # Google extendedProperties.private (string -> string map). Used to detect
    # events that this app wrote (task_scheduler="1") so they can be excluded
    # from busy-time computation during re-optimization.
    extended_properties_private: dict[str, str] = {}


class CalendarInfo(BaseModel):
    id: str
    summary: str
    description: str | None
    primary: bool
    access_role: Literal["owner", "writer", "reader", "freeBusyReader"]
    background_color: str | None
    selected: bool
    time_zone: str | None
    source: Literal["google"] = "google"
