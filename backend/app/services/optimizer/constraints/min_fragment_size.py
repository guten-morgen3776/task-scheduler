from app.services.optimizer.constraints.base import Constraint
from app.services.optimizer.domain import BuildContext


class MinFragmentSizeConstraint(Constraint):
    """min_fragment * y[i,j] <= x[i,j] <= ub * y[i,j].

    If x > 0 then y = 1 and x >= min_fragment.
    Avoids 5-minute fragments while still allowing tasks to be split.
    """

    name = "min_fragment_size"

    def apply(self, ctx: BuildContext) -> None:
        m = ctx.config.min_fragment_min
        for task in ctx.tasks:
            for slot in ctx.slots:
                ub = min(slot.duration_min, task.duration_min)
                x = ctx.x[task.id, slot.id]
                y = ctx.y[task.id, slot.id]
                # x <= ub * y  ensures y=0 -> x=0
                ctx.backend.add_constraint(
                    x <= ub * y,
                    name=f"{self.name}_upper__{task.id}__{slot.id}",
                )
                # m * y <= x  ensures y=1 -> x >= m
                ctx.backend.add_constraint(
                    m * y <= x,
                    name=f"{self.name}_lower__{task.id}__{slot.id}",
                )
