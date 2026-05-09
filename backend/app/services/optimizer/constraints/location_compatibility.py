from app.services.optimizer.constraints.base import Constraint
from app.services.optimizer.domain import BuildContext


class LocationCompatibilityConstraint(Constraint):
    """x[i,j] = 0 if task and slot have incompatible specific locations.

    Compatibility rules:
    - task.location is None or "anywhere" → no constraint (task fits anywhere)
    - slot.location == "anywhere" → any task fits (open slot)
    - otherwise the two must match exactly
    """

    name = "location_compatibility"

    def apply(self, ctx: BuildContext) -> None:
        for task in ctx.tasks:
            t_loc = task.location
            if t_loc is None or t_loc == "anywhere":
                continue
            for slot in ctx.slots:
                s_loc = slot.location
                if s_loc == "anywhere":
                    continue
                if s_loc != t_loc:
                    ctx.backend.add_constraint(
                        ctx.x[task.id, slot.id] == 0,
                        name=f"{self.name}__{task.id}__{slot.id}",
                    )
