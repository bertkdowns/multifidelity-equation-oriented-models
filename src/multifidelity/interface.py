"""The shared physical interface supplied to fidelity builders."""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class SharedHX:
    time: Any
    hot_inlet: Any
    hot_outlet: Any
    cold_inlet: Any
    cold_outlet: Any
    area: Any
    U: Any
    length: Any
    heat_duty: Any


class Fidelity(Protocol):
    def build(self, block, shared: SharedHX) -> None: ...

    def initialize(self, block, shared: SharedHX, *, solver) -> Any: ...
