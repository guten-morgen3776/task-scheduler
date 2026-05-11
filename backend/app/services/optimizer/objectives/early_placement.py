from app.services.optimizer.domain import BuildContext
from app.services.optimizer.objectives.base import ObjectiveTerm


class EarlyPlacementObjective(ObjectiveTerm):
    """Soft preference: among slots that fit before a task's deadline, prefer
    the earlier ones. Stops the optimizer from leaving deadlined tasks for
    the last day available.

    + w_early_placement * Σᵢⱼ slack_ratio_ij * x[i, j]

    For each (task i with a deadline, slot j) pair:

        slack_ratio = (deadline_i - slot_j.end) / (deadline_i - reference)

    where `reference` is the earliest slot's start (acts as "now" for the
    optimization). The ratio falls in (0, 1]: 1 for the earliest possible
    slot, ~0 for slots that end right at the deadline.

    Normalized by the task's own deadline horizon, so a task due tomorrow
    and a task due next week are treated proportionally — both prefer the
    earliest slot within their respective windows. (Cross-task urgency
    weighting is handled by `urgency` separately.)

    Tasks without a deadline contribute nothing. Slots past a task's
    deadline are excluded by `DeadlineConstraint`; we just skip them here.
    """

    name = "early_placement"

    def contribute(self, ctx: BuildContext) -> None:
        w = ctx.config.weights.get(self.name, 0.0)
        if w <= 0 or not ctx.slots:
            return

        reference = min(s.start for s in ctx.slots)

        for task in ctx.tasks:
            if task.deadline is None:
                continue
            horizon_sec = (task.deadline - reference).total_seconds()
            if horizon_sec <= 0:
                # Deadline already past or at the very first slot — no room
                # for an "earliness" gradient. urgency / force_deadlined still
                # apply.
                continue
            for slot in ctx.slots:
                slack_sec = (task.deadline - slot.end).total_seconds()
                if slack_sec <= 0:
                    continue
                ratio = slack_sec / horizon_sec
                ctx.backend.add_to_objective(
                    w * ratio * ctx.x[task.id, slot.id]
                )
