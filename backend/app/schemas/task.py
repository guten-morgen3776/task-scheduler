from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


Priority = Annotated[int, Field(ge=1, le=5)]
DurationMin = Annotated[int, Field(gt=0)]
Location = Literal["home", "university", "office", "anywhere"]


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    notes: str | None = None
    parent_id: str | None = None
    due: datetime | None = None
    duration_min: DurationMin = 60
    priority: Priority = 3
    deadline: datetime | None = None
    location: Location | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    notes: str | None = None
    parent_id: str | None = None
    due: datetime | None = None
    duration_min: DurationMin | None = None
    priority: Priority | None = None
    deadline: datetime | None = None
    location: Location | None = None


class TaskMove(BaseModel):
    list_id: str | None = None
    position: str | None = None


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    list_id: str
    title: str
    notes: str | None
    parent_id: str | None
    position: str
    completed: bool
    completed_at: datetime | None
    due: datetime | None
    duration_min: int
    priority: int
    deadline: datetime | None
    location: Location | None
    scheduled_event_id: str | None
    scheduled_start: datetime | None
    scheduled_end: datetime | None
    created_at: datetime
    updated_at: datetime


class TaskReadWithSubtasks(TaskRead):
    subtasks: list[TaskRead] = Field(default_factory=list)
