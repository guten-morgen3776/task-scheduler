from abc import ABC, abstractmethod

from app.services.optimizer.domain import BuildContext


class ObjectiveTerm(ABC):
    name: str

    @abstractmethod
    def contribute(self, ctx: BuildContext) -> None: ...
