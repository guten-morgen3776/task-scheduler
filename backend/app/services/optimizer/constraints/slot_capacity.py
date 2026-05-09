from app.services.optimizer.constraints.base import Constraint
from app.services.optimizer.domain import BuildContext


class SlotCapacityConstraint(Constraint):
    """sum_i x[i,j] <= duration_j.

    The total minutes assigned to a slot can't exceed its length.
    """

    name = "slot_capacity"

    def apply(self, ctx: BuildContext) -> None:
        for slot in ctx.slots:
            assigned = [ctx.x[task.id, slot.id] for task in ctx.tasks]
            ctx.backend.add_constraint(
                sum(assigned) <= slot.duration_min,
                name=f"{self.name}__{slot.id}",
            )
