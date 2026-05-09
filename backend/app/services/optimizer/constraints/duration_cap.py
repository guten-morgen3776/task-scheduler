from app.services.optimizer.constraints.base import Constraint
from app.services.optimizer.domain import BuildContext


class DurationCapConstraint(Constraint):
    """x[i,j] = 0 if task_i.duration_min > slot_j.allowed_max_task_duration_min.

    A whole task that is longer than the slot's per-task duration cap is fully
    excluded from that slot, even if it could fit by being split. This preserves
    the original semantic ("don't do long/heavy tasks on intern day").
    """

    name = "duration_cap"

    def apply(self, ctx: BuildContext) -> None:
        for task in ctx.tasks:
            for slot in ctx.slots:
                if task.duration_min > slot.allowed_max_task_duration_min:
                    ctx.backend.add_constraint(
                        ctx.x[task.id, slot.id] == 0,
                        name=f"{self.name}__{task.id}__{slot.id}",
                    )
