from abc import ABC, abstractmethod
from typing import Any, Literal

SolveStatus = Literal["optimal", "feasible", "infeasible", "timed_out", "error"]


class SolverBackend(ABC):
    @abstractmethod
    def add_binary_var(self, name: str) -> Any: ...

    @abstractmethod
    def add_int_var(self, name: str, lb: int, ub: int) -> Any: ...

    @abstractmethod
    def add_constraint(self, expr: Any, name: str) -> None: ...

    @abstractmethod
    def add_to_objective(self, expr: Any) -> None: ...

    @abstractmethod
    def set_sense_maximize(self) -> None: ...

    @abstractmethod
    def solve(self, time_limit_sec: int) -> SolveStatus: ...

    @abstractmethod
    def value(self, var: Any) -> float: ...

    @abstractmethod
    def objective_value(self) -> float | None: ...
