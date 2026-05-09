from datetime import datetime

from app.core.time import utc_now
from app.services.optimizer.domain import BuildContext
from app.services.optimizer.objectives.base import ObjectiveTerm


def _urgency_score(task_deadline: datetime | None, now: datetime) -> float:
    """1 / (days_until_deadline + 1). No deadline = 0."""
    if task_deadline is None:
        return 0.0
    days = max((task_deadline - now).total_seconds() / 86400.0, 0.0)
    return 1.0 / (days + 1.0)


class UrgencyObjective(ObjectiveTerm):
    """Reward placing tasks whose deadline is near: w * sum_i urgency_i * z_i."""

    name = "urgency"

    def contribute(self, ctx: BuildContext) -> None:
        w = ctx.config.weights.get(self.name, 0.0)
        if w == 0:
            return
        now = utc_now()
        for task in ctx.tasks:
            score = _urgency_score(task.deadline, now)
            if score == 0:
                continue
            ctx.backend.add_to_objective(w * score * ctx.z[task.id])
