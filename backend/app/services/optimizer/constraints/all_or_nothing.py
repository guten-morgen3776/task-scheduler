from app.services.optimizer.constraints.base import Constraint
from app.services.optimizer.domain import BuildContext


class AllOrNothingConstraint(Constraint):
    """sum_j x[i,j] = duration_i * z[i].

    A task is fully scheduled (sum of fragments = duration) or not at all (sum = 0).
    """

    name = "all_or_nothing"

    def apply(self, ctx: BuildContext) -> None:
        for task in ctx.tasks:
            fragments = [ctx.x[task.id, slot.id] for slot in ctx.slots]
            ctx.backend.add_constraint(
                sum(fragments) == task.duration_min * ctx.z[task.id],
                name=f"{self.name}__{task.id}",
            )
