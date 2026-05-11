from app.services.optimizer.constraints.base import Constraint
from app.services.optimizer.domain import BuildContext


class ForceDeadlinedConstraint(Constraint):
    """z[i] = 1 for every task with a deadline.

    Combined with `DeadlineConstraint` (which blocks placement past the
    deadline), this makes "place every deadlined task before its deadline" an
    absolute requirement, not a weighted preference. If no compatible slots
    exist in time, the model returns `infeasible` — caller should surface
    which task(s) couldn't fit so the user can extend the range or remove
    the task.
    """

    name = "force_deadlined"

    def apply(self, ctx: BuildContext) -> None:
        for task in ctx.tasks:
            if task.deadline is None:
                continue
            ctx.backend.add_constraint(
                ctx.z[task.id] == 1,
                name=f"{self.name}__{task.id}",
            )
