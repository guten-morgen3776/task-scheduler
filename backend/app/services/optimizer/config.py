from typing import Literal

from pydantic import BaseModel, Field


DEFAULT_WEIGHTS: dict[str, float] = {
    "priority": 1.0,
    "urgency": 1.0,
    "energy_match": 0.05,
    "unassigned_penalty": 5.0,
    # KeepTogetherObjective uses two separate weight keys:
    # - keep_together_fragments: penalty per slot a task occupies
    # - keep_together_days:      penalty per distinct date a task spans
    # Calibrated so a fragment costs roughly the energy_match gain of moving
    # 20 minutes from a low-energy fallback slot (0.21) to a normal slot (0.7);
    # tasks that fit in one slot reliably stay there, and the optimizer only
    # splits when it physically must (e.g., the task is larger than any single
    # slot before the deadline).
    "keep_together_fragments": 1.0,
    "keep_together_days": 2.0,
    # Per-minute bonus for placing deadlined tasks early within their window.
    # Scales by `(deadline - slot.end) / (deadline - earliest_slot.start)` so
    # a task due tomorrow vs next week prefer the same "earliest fraction" of
    # their own horizon. Soft — energy_match (0.05 × minutes × energy) usually
    # wins close decisions, but identical-energy candidates flip to earlier.
    "early_placement": 0.02,
}

DEFAULT_ENABLED_CONSTRAINTS: set[str] = {
    "all_or_nothing",
    "slot_capacity",
    "deadline",
    "force_deadlined",
    "duration_cap",
    "min_fragment_size",
    "max_fragments",
    "location_compatibility",
}

DEFAULT_ENABLED_OBJECTIVES: set[str] = {
    "priority",
    "urgency",
    "energy_match",
    "unassigned_penalty",
    "keep_together",
    "early_placement",
}


class OptimizerConfig(BaseModel):
    weights: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    enabled_constraints: set[str] = Field(
        default_factory=lambda: set(DEFAULT_ENABLED_CONSTRAINTS)
    )
    enabled_objectives: set[str] = Field(
        default_factory=lambda: set(DEFAULT_ENABLED_OBJECTIVES)
    )
    min_fragment_min: int = Field(default=30, gt=0)
    max_fragments_per_task: int | None = Field(default=5, gt=0)
    time_limit_sec: int = Field(default=30, gt=0)
    backend: Literal["pulp"] = "pulp"

    def merge(self, overrides: "OptimizerConfigUpdate") -> "OptimizerConfig":
        data = self.model_dump()
        patch = overrides.model_dump(exclude_unset=True)
        if "weights" in patch and patch["weights"] is not None:
            merged_weights = dict(data["weights"])
            merged_weights.update(patch["weights"])
            data["weights"] = merged_weights
            del patch["weights"]
        data.update({k: v for k, v in patch.items() if v is not None})
        return OptimizerConfig.model_validate(data)


class OptimizerConfigUpdate(BaseModel):
    weights: dict[str, float] | None = None
    enabled_constraints: set[str] | None = None
    enabled_objectives: set[str] | None = None
    min_fragment_min: int | None = Field(default=None, gt=0)
    max_fragments_per_task: int | None = Field(default=None, gt=0)
    time_limit_sec: int | None = Field(default=None, gt=0)
    backend: Literal["pulp"] | None = None
