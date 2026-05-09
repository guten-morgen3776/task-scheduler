from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services.optimizer.config import OptimizerConfigUpdate


class OptimizeRequest(BaseModel):
    start: datetime
    end: datetime
    list_ids: list[str] | None = None
    task_ids: list[str] | None = None
    config_overrides: OptimizerConfigUpdate | None = None
    note: str | None = None


class FragmentRead(BaseModel):
    slot_id: str
    start: datetime
    duration_min: int


class TaskAssignmentRead(BaseModel):
    task_id: str
    task_title: str
    fragments: list[FragmentRead]
    total_assigned_min: int


class UnassignedRead(BaseModel):
    task_id: str
    task_title: str


class OptimizeResponse(BaseModel):
    status: Literal["optimal", "feasible", "infeasible", "timed_out", "error"]
    objective_value: float | None
    snapshot_id: str
    assignments: list[TaskAssignmentRead]
    unassigned: list[UnassignedRead]
    solve_time_sec: float
    notes: list[str] = Field(default_factory=list)


class SnapshotSummary(BaseModel):
    id: str
    created_at: datetime
    note: str | None
    status: str | None
    task_count: int
    slot_count: int


class SnapshotDetail(BaseModel):
    id: str
    created_at: datetime
    note: str | None
    tasks_json: list[dict[str, Any]]
    slots_json: list[dict[str, Any]]
    config_json: dict[str, Any]
    result_json: dict[str, Any] | None


class ReplayRequest(BaseModel):
    config_overrides: OptimizerConfigUpdate | None = None
    note: str | None = None


class WriteRequest(BaseModel):
    dry_run: bool = False
    target_calendar_id: str = "primary"


class WrittenEventRead(BaseModel):
    task_id: str
    task_title: str
    event_id: str | None
    start: datetime
    end: datetime
    fragment_index: int


class WriteResponse(BaseModel):
    snapshot_id: str
    dry_run: bool
    target_calendar_id: str
    deleted_event_count: int
    created_events: list[WrittenEventRead]


class DeleteWriteResponse(BaseModel):
    deleted_event_count: int
    target_calendar_id: str
