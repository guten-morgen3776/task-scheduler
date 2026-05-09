from abc import ABC, abstractmethod

from app.services.optimizer.domain import BuildContext


class Constraint(ABC):
    name: str

    @abstractmethod
    def apply(self, ctx: BuildContext) -> None: ...
