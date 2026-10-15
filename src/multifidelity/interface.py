"""The shared physical interface supplied to fidelity builders."""

from dataclasses import dataclass
from typing import Protocol, TypeVar

from idaes.core import StateBlock
from pyomo.core.base.block import BlockData
from pyomo.core.base.expression import IndexedExpression
from pyomo.core.base.set import Set
from pyomo.core.base.var import IndexedVar, ScalarVar
from pyomo.opt import SolverResults
from pyomo.opt.base.solvers import OptSolver


@dataclass(frozen=True)
class SharedHX:
    time: Set
    hot_inlet: StateBlock
    hot_outlet: StateBlock
    cold_inlet: StateBlock
    cold_outlet: StateBlock
    area: ScalarVar
    U: IndexedVar
    length: ScalarVar
    heat_duty: IndexedExpression


SharedT = TypeVar("SharedT", contravariant=True)


class Fidelity(Protocol[SharedT]):
    def build(self, block: BlockData, shared: SharedT) -> None: ...

    def initialize(
        self,
        block: BlockData,
        shared: SharedT,
        *,
        equipment: BlockData,
        solver: OptSolver,
    ) -> SolverResults: ...
