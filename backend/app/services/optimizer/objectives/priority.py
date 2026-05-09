from app.services.optimizer.domain import BuildContext
from app.services.optimizer.objectives.base import ObjectiveTerm


class PriorityObjective(ObjectiveTerm):
    """Reward assigning high-priority tasks: w * sum_i (priority_i / 5) * z_i."""

    name = "priority"

    def contribute(self, ctx: BuildContext) -> None:
        w = ctx.config.weights.get(self.name, 0.0)
        if w == 0:
            return
        for task in ctx.tasks:
            score = (task.priority / 5.0) * ctx.z[task.id]
            ctx.backend.add_to_objective(w * score)
