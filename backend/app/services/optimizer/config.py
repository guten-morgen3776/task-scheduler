from typing import Literal

from pydantic import BaseModel, Field


DEFAULT_WEIGHTS: dict[str, float] = {
    "priority": 1.0,
    "urgency": 1.0,
    "energy_match": 0.05,
    "unassigned_penalty": 5.0,
}

DEFAULT_ENABLED_CONSTRAINTS: set[str] = {
    "all_or_nothing",
    "slot_capacity",
    "deadline",
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
