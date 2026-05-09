from app.services.optimizer.domain import BuildContext
from app.services.optimizer.objectives.base import ObjectiveTerm


class UnassignedPenaltyObjective(ObjectiveTerm):
    """Penalize leaving tasks unassigned, weighted by priority:

        - w * sum_i (priority_i / 5) * (1 - z_i)

    High-priority unassigned tasks hurt more than low-priority ones.
    """

    name = "unassigned_penalty"

    def contribute(self, ctx: BuildContext) -> None:
        w = ctx.config.weights.get(self.name, 0.0)
        if w == 0:
            return
        for task in ctx.tasks:
            penalty = (task.priority / 5.0) * (1 - ctx.z[task.id])
            ctx.backend.add_to_objective(-w * penalty)
