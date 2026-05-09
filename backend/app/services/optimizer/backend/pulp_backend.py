import logging
from typing import Any

import pulp

from app.services.optimizer.backend.base import SolveStatus, SolverBackend

logger = logging.getLogger("app.optimizer")


class PuLPBackend(SolverBackend):
    def __init__(self, problem_name: str = "task_scheduler") -> None:
        self._problem = pulp.LpProblem(problem_name, pulp.LpMaximize)
        self._objective_terms: list[Any] = []
        self._sense_set = False

    def add_binary_var(self, name: str) -> pulp.LpVariable:
        return pulp.LpVariable(name, cat="Binary")

    def add_int_var(self, name: str, lb: int, ub: int) -> pulp.LpVariable:
        return pulp.LpVariable(name, lowBound=lb, upBound=ub, cat="Integer")

    def add_constraint(self, expr: Any, name: str) -> None:
        # PuLP requires unique constraint names
        self._problem += expr, name

    def add_to_objective(self, expr: Any) -> None:
        self._objective_terms.append(expr)

    def set_sense_maximize(self) -> None:
        self._problem.sense = pulp.LpMaximize
        self._sense_set = True

    def solve(self, time_limit_sec: int) -> SolveStatus:
        if self._objective_terms:
            self._problem += pulp.lpSum(self._objective_terms)
        else:
            # Pulp requires an objective expression even when we only need feasibility
            self._problem += 0
        solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit_sec)
        try:
            self._problem.solve(solver)
        except Exception as e:
            logger.exception("PuLP solve raised: %s", e)
            return "error"
        return _map_status(self._problem.status, self._problem.sol_status)

    def value(self, var: Any) -> float:
        v = pulp.value(var)
        return float(v) if v is not None else 0.0

    def objective_value(self) -> float | None:
        if self._problem.objective is None:
            return None
        v = pulp.value(self._problem.objective)
        return float(v) if v is not None else None


def _map_status(lp_status: int, sol_status: int) -> SolveStatus:
    """Map PuLP status codes to our SolveStatus."""
    # pulp.LpStatus: 1=Optimal, 0=Not Solved, -1=Infeasible, -2=Unbounded, -3=Undefined
    # pulp.LpSolution: -3=NoSolutionFound, -2=Infeasible, -1=Unbounded, 0=NotSolved, 1=Optimal, 2=Integer Feasible
    if lp_status == 1:
        return "optimal"
    if sol_status == 2:
        return "feasible"
    if lp_status == -1 or sol_status == -2:
        return "infeasible"
    if lp_status == 0 or sol_status in (-3, 0):
        return "timed_out"
    return "error"
