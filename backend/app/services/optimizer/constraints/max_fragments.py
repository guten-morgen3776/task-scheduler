from app.services.optimizer.constraints.base import Constraint
from app.services.optimizer.domain import BuildContext


class MaxFragmentsConstraint(Constraint):
    """sum_j y[i,j] <= max_fragments_per_task.

    Caps the number of slots a single task can be split across.
    """

    name = "max_fragments"

    def apply(self, ctx: BuildContext) -> None:
        cap = ctx.config.max_fragments_per_task
        if cap is None:
            return
        for task in ctx.tasks:
            fragments = [ctx.y[task.id, slot.id] for slot in ctx.slots]
            ctx.backend.add_constraint(
                sum(fragments) <= cap,
                name=f"{self.name}__{task.id}",
            )
