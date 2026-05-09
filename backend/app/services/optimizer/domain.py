from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.settings import Location


@dataclass(frozen=True)
class OptimizerTask:
    id: str
    title: str
    duration_min: int
    deadline: datetime | None  # UTC, tz-aware. None = no hard deadline
    priority: int
    location: Location | None = None  # None / "anywhere" = no constraint


@dataclass(frozen=True)
class OptimizerSlot:
    id: str
    start: datetime  # UTC, tz-aware
    duration_min: int
    energy_score: float
    allowed_max_task_duration_min: int
    day_type: str
    location: Location

    @property
    def end(self) -> datetime:
        from datetime import timedelta

        return self.start + timedelta(minutes=self.duration_min)


class Fragment(BaseModel):
    """1 タスクの 1 スロット内の断片（永続化されないが API で返す）。"""

    model_config = ConfigDict(frozen=True)

    task_id: str
    slot_id: str
    start: datetime
    duration_min: int


class TaskAssignment(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    fragments: list[Fragment]
    total_assigned_min: int


SolveStatus = Literal["optimal", "feasible", "infeasible", "timed_out", "error"]


class SolveResult(BaseModel):
    status: SolveStatus
    objective_value: float | None
    assignments: list[TaskAssignment]
    unassigned_task_ids: list[str]
    solve_time_sec: float
    notes: list[str] = []


@dataclass
class BuildContext:
    """Mutable context shared by constraints and objective terms during model building."""

    tasks: list[OptimizerTask]
    slots: list[OptimizerSlot]
    backend: "object"  # SolverBackend (avoid circular import)
    config: "object"   # OptimizerConfig

    # Decision variables — populated by Optimizer.create_decision_variables()
    z: dict[str, object] = field(default_factory=dict)        # z[task_id]
    x: dict[tuple[str, str], object] = field(default_factory=dict)  # x[task_id, slot_id]
    y: dict[tuple[str, str], object] = field(default_factory=dict)  # y[task_id, slot_id]

    def task_by_id(self, task_id: str) -> OptimizerTask:
        for t in self.tasks:
            if t.id == task_id:
                return t
        raise KeyError(task_id)

    def slot_by_id(self, slot_id: str) -> OptimizerSlot:
        for s in self.slots:
            if s.id == slot_id:
                return s
        raise KeyError(slot_id)
