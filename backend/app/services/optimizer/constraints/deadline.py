from app.services.optimizer.constraints.base import Constraint
from app.services.optimizer.domain import BuildContext


class DeadlineConstraint(Constraint):
    """x[i,j] = 0 if slot_j ends after task_i.deadline.

    Tasks with no deadline are unrestricted.
    """

    name = "deadline"

    def apply(self, ctx: BuildContext) -> None:
        for task in ctx.tasks:
            if task.deadline is None:
                continue
            for slot in ctx.slots:
                if slot.end > task.deadline:
                    ctx.backend.add_constraint(
                        ctx.x[task.id, slot.id] == 0,
                        name=f"{self.name}__{task.id}__{slot.id}",
                    )
