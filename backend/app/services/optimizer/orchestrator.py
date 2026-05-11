import logging
import time
from collections.abc import Callable
from datetime import timedelta

from app.services.optimizer.backend.base import SolverBackend
from app.services.optimizer.backend.pulp_backend import PuLPBackend
from app.services.optimizer.config import OptimizerConfig
from app.services.optimizer.constraints.all_or_nothing import AllOrNothingConstraint
from app.services.optimizer.constraints.base import Constraint
from app.services.optimizer.constraints.deadline import DeadlineConstraint
from app.services.optimizer.constraints.duration_cap import DurationCapConstraint
from app.services.optimizer.constraints.force_deadlined import (
    ForceDeadlinedConstraint,
)
from app.services.optimizer.constraints.location_compatibility import (
    LocationCompatibilityConstraint,
)
from app.services.optimizer.constraints.max_fragments import MaxFragmentsConstraint
from app.services.optimizer.constraints.min_fragment_size import MinFragmentSizeConstraint
from app.services.optimizer.constraints.slot_capacity import SlotCapacityConstraint
from app.services.optimizer.domain import (
    BuildContext,
    Fragment,
    OptimizerSlot,
    OptimizerTask,
    SolveResult,
    TaskAssignment,
)
from app.services.optimizer.objectives.base import ObjectiveTerm
from app.services.optimizer.objectives.early_placement import EarlyPlacementObjective
from app.services.optimizer.objectives.energy_match import EnergyMatchObjective
from app.services.optimizer.objectives.keep_together import KeepTogetherObjective
from app.services.optimizer.objectives.priority import PriorityObjective
from app.services.optimizer.objectives.unassigned_penalty import UnassignedPenaltyObjective
from app.services.optimizer.objectives.urgency import UrgencyObjective

logger = logging.getLogger("app.optimizer")


def default_constraints() -> list[Constraint]:
    return [
        AllOrNothingConstraint(),
        SlotCapacityConstraint(),
        DeadlineConstraint(),
        ForceDeadlinedConstraint(),
        DurationCapConstraint(),
        MinFragmentSizeConstraint(),
        MaxFragmentsConstraint(),
        LocationCompatibilityConstraint(),
    ]


def default_objectives() -> list[ObjectiveTerm]:
    return [
        PriorityObjective(),
        UrgencyObjective(),
        EnergyMatchObjective(),
        UnassignedPenaltyObjective(),
        KeepTogetherObjective(),
        EarlyPlacementObjective(),
    ]


def default_backend_factory(config: OptimizerConfig) -> Callable[[], SolverBackend]:
    if config.backend == "pulp":
        return lambda: PuLPBackend()
    raise ValueError(f"Unknown backend: {config.backend}")


class Optimizer:
    def __init__(
        self,
        config: OptimizerConfig | None = None,
        constraints: list[Constraint] | None = None,
        objectives: list[ObjectiveTerm] | None = None,
        backend_factory: Callable[[], SolverBackend] | None = None,
    ) -> None:
        self.config = config or OptimizerConfig()
        self.constraints = constraints if constraints is not None else default_constraints()
        self.objectives = objectives if objectives is not None else default_objectives()
        self.backend_factory = backend_factory or default_backend_factory(self.config)

    def solve(
        self, tasks: list[OptimizerTask], slots: list[OptimizerSlot]
    ) -> SolveResult:
        start_time = time.perf_counter()

        if not tasks:
            return SolveResult(
                status="optimal",
                objective_value=0.0,
                assignments=[],
                unassigned_task_ids=[],
                solve_time_sec=time.perf_counter() - start_time,
                notes=["no tasks to schedule"],
            )

        backend = self.backend_factory()
        backend.set_sense_maximize()

        ctx = BuildContext(
            tasks=tasks, slots=slots, backend=backend, config=self.config
        )
        self._create_decision_variables(ctx)

        for c in self._enabled(self.constraints, self.config.enabled_constraints):
            c.apply(ctx)

        for o in self._enabled(self.objectives, self.config.enabled_objectives):
            o.contribute(ctx)

        status = backend.solve(self.config.time_limit_sec)
        obj_value = backend.objective_value() if status in {"optimal", "feasible"} else None

        result = self._extract_result(
            ctx, status, obj_value, time.perf_counter() - start_time
        )
        return result

    def _enabled(self, items, enabled_set: set[str]):
        return [it for it in items if it.name in enabled_set]

    def _create_decision_variables(self, ctx: BuildContext) -> None:
        for task in ctx.tasks:
            ctx.z[task.id] = ctx.backend.add_binary_var(f"z__{task.id}")
        for task in ctx.tasks:
            for slot in ctx.slots:
                ub = min(task.duration_min, slot.duration_min)
                ctx.x[task.id, slot.id] = ctx.backend.add_int_var(
                    f"x__{task.id}__{slot.id}", lb=0, ub=ub
                )
                ctx.y[task.id, slot.id] = ctx.backend.add_binary_var(
                    f"y__{task.id}__{slot.id}"
                )

    def _extract_result(
        self,
        ctx: BuildContext,
        status: str,
        objective_value: float | None,
        elapsed_sec: float,
    ) -> SolveResult:
        if status not in {"optimal", "feasible"}:
            notes: list[str] = []
            if status == "infeasible":
                notes = _diagnose_deadline_infeasibility(ctx.tasks, ctx.slots)
                if not notes:
                    notes = [
                        "infeasible: deadline tasks fit pre-deadline individually "
                        "but compete for the same slots — try widening the range "
                        "or relaxing duration_cap/min_fragment_size"
                    ]
            return SolveResult(
                status=status,
                objective_value=None,
                assignments=[],
                unassigned_task_ids=[t.id for t in ctx.tasks],
                solve_time_sec=elapsed_sec,
                notes=notes,
            )

        backend = ctx.backend
        unassigned: list[str] = []
        assigned_ids: list[str] = []
        for task in ctx.tasks:
            z_val = round(backend.value(ctx.z[task.id]))
            if z_val < 1:
                unassigned.append(task.id)
            else:
                assigned_ids.append(task.id)

        # Group placements by slot first so multiple tasks sharing a slot get
        # sequential, non-overlapping offsets. (slot_capacity allows packing
        # several tasks into one slot — they must be placed back-to-back.)
        slot_placements: dict[str, list[tuple[str, int]]] = {}
        for task_id in assigned_ids:
            for slot in ctx.slots:
                minutes = round(backend.value(ctx.x[task_id, slot.id]))
                if minutes <= 0:
                    continue
                slot_placements.setdefault(slot.id, []).append((task_id, minutes))

        task_fragments: dict[str, list[Fragment]] = {tid: [] for tid in assigned_ids}
        for slot in ctx.slots:
            offset = 0
            for task_id, minutes in slot_placements.get(slot.id, []):
                task_fragments[task_id].append(
                    Fragment(
                        task_id=task_id,
                        slot_id=slot.id,
                        start=slot.start + timedelta(minutes=offset),
                        duration_min=minutes,
                    )
                )
                offset += minutes

        assignments: list[TaskAssignment] = []
        for task in ctx.tasks:
            if task.id in unassigned:
                assignments.append(
                    TaskAssignment(task_id=task.id, fragments=[], total_assigned_min=0)
                )
                continue
            frags = sorted(task_fragments[task.id], key=lambda f: f.start)
            assignments.append(
                TaskAssignment(
                    task_id=task.id,
                    fragments=frags,
                    total_assigned_min=sum(f.duration_min for f in frags),
                )
            )

        return SolveResult(
            status=status,
            objective_value=objective_value,
            assignments=assignments,
            unassigned_task_ids=unassigned,
            solve_time_sec=elapsed_sec,
        )


def _diagnose_deadline_infeasibility(
    tasks: list[OptimizerTask], slots: list[OptimizerSlot]
) -> list[str]:
    """Identify deadlined tasks that individually can't fit before their deadline.

    Counts slot minutes that are (a) before the deadline, (b) location-compatible,
    and (c) have a per-task duration cap that admits this task's full duration.
    Does NOT account for inter-task slot competition, so an empty result means
    each deadline task fits on its own but they collide somewhere — see the
    fallback note in the caller.
    """
    notes: list[str] = []
    for t in tasks:
        if t.deadline is None:
            continue
        usable_min = 0
        for s in slots:
            if s.end > t.deadline:
                continue
            # Mirrors LocationCompatibilityConstraint logic.
            if (
                t.location is not None
                and t.location != "anywhere"
                and s.location != "anywhere"
                and s.location != t.location
            ):
                continue
            # Mirrors DurationCapConstraint: a task longer than the cap is
            # fully excluded from that slot.
            if t.duration_min > s.allowed_max_task_duration_min:
                continue
            usable_min += s.duration_min
        if usable_min < t.duration_min:
            notes.append(
                f"task '{t.title}' ({t.duration_min}min, deadline "
                f"{t.deadline.isoformat()}) cannot fit: only {usable_min}min of "
                f"compatible slots before the deadline"
            )
    return notes
