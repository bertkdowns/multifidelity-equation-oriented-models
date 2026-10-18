"""The shared physical interface supplied to fidelity builders."""

from dataclasses import dataclass

from idaes.core import StateBlock
from pyomo.core.base.expression import IndexedExpression
from pyomo.core.base.set import Set
from pyomo.core.base.var import IndexedVar, ScalarVar


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
    hot_pressure_drop: IndexedVar
    cold_pressure_drop: IndexedVar
