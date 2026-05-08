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
