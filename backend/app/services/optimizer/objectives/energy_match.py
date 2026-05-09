from app.services.optimizer.domain import BuildContext
from app.services.optimizer.objectives.base import ObjectiveTerm


class EnergyMatchObjective(ObjectiveTerm):
    """Reward placing minutes in high-energy slots:

        w * sum_{i,j} slot.energy_score * x[i,j]

    Per-minute weighted: longer tasks gain more from being in high-energy slots,
    so they naturally win those slots over short tasks. Short tasks fall to
    leftover lower-energy slots.

    Note: Phase 3 simplification — `weight` per task was dropped. The original
    `(1 - |task.weight - slot.energy|)` match scoring is now just `slot.energy`
    weighted by minutes assigned.
    """

    name = "energy_match"

    def contribute(self, ctx: BuildContext) -> None:
        w = ctx.config.weights.get(self.name, 0.0)
        if w == 0:
            return
        for task in ctx.tasks:
            for slot in ctx.slots:
                if slot.energy_score <= 0:
                    continue
                ctx.backend.add_to_objective(w * slot.energy_score * ctx.x[task.id, slot.id])
