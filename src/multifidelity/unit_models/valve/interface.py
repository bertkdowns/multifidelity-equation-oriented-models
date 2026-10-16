"""Shared mass-based liquid-valve state and approximation point."""

from dataclasses import dataclass

from idaes.core import StateBlock
from pyomo.core.base.expression import IndexedExpression, ScalarExpression
from pyomo.core.base.param import ScalarParam
from pyomo.core.base.set import Set
from pyomo.core.base.var import IndexedVar, ScalarVar


@dataclass(frozen=True)
class SharedValve:
    time: Set
    inlet: StateBlock
    outlet: StateBlock
    Cv: ScalarVar
    opening: IndexedVar
    alpha: ScalarParam
    pressure_drop: IndexedExpression
    nonlinear_residual: IndexedExpression
    basic_residual: IndexedExpression
    nominal_flow: ScalarExpression
    nominal_Cv: ScalarParam
    nominal_pressure_drop: ScalarParam
    nominal_density: ScalarParam
    nominal_opening: ScalarParam
