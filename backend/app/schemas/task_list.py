from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TaskListCreate(BaseModel):
    title: str = Field(min_length=1, max_length=512)


class TaskListUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    position: str | None = None


class TaskListRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    position: str
    created_at: datetime
    updated_at: datetime


class TaskListReadWithCounts(TaskListRead):
    task_count: int
    completed_count: int
