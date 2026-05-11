from collections import defaultdict

from app.services.optimizer.domain import BuildContext
from app.services.optimizer.objectives.base import ObjectiveTerm


class KeepTogetherObjective(ObjectiveTerm):
    """Soft preference: keep a single task's fragments together in time.

    Two penalty axes — both subtracted from the objective:
      - `keep_together_fragments` * Σ_{i,j} y[i,j]
          (more slots used by a task → bigger penalty;
           encourages a single contiguous chunk)
      - `keep_together_days`      * Σ_{i,date} d[i,date]
          (more distinct dates a task spans → bigger penalty;
           encourages "wrap it up in one day" over "spread across the week")

    `d[i,date]` is a new auxiliary binary linked via
        d[i,date] >= y[i,j]   for each slot j on that date
    Maximization naturally drives d down to 0 when no slot on that date is
    used (because the term is negative), so no upper-bound constraint is
    needed.

    Soft by design — defaults are small enough that priority/urgency/
    energy_match can still justify a split when there's a real benefit to
    spreading. Tune `keep_together_*` weights upward if the user finds the
    optimizer over-splits.

    Day grouping uses the slot's UTC date. For the JST timezone with work
    hours up to 23:59 local, that's identical to local-date grouping. Other
    timezones with day-crossing extensions would need explicit local-date
    handling.
    """

    name = "keep_together"

    def contribute(self, ctx: BuildContext) -> None:
        w_frag = ctx.config.weights.get("keep_together_fragments", 0.0)
        w_day = ctx.config.weights.get("keep_together_days", 0.0)
        if w_frag <= 0 and w_day <= 0:
            return

        if w_frag > 0:
            for task in ctx.tasks:
                for slot in ctx.slots:
                    ctx.backend.add_to_objective(
                        -w_frag * ctx.y[task.id, slot.id]
                    )

        if w_day > 0:
            slots_by_date: dict[str, list] = defaultdict(list)
            for slot in ctx.slots:
                slots_by_date[slot.start.date().isoformat()].append(slot)

            for task in ctx.tasks:
                for date_key, day_slots in slots_by_date.items():
                    d_var = ctx.backend.add_binary_var(
                        f"d__{task.id}__{date_key}"
                    )
                    for slot in day_slots:
                        ctx.backend.add_constraint(
                            d_var >= ctx.y[task.id, slot.id],
                            name=f"keep_together_day__{task.id}__{date_key}__{slot.id}",
                        )
                    ctx.backend.add_to_objective(-w_day * d_var)
