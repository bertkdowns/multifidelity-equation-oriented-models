"""An affine, constant-cp liquid-water approximation around room temperature."""

from typing import TYPE_CHECKING

from pyomo.core.base.block import BlockData
from pyomo.environ import Constraint
from pyomo.opt import SolverResults
from pyomo.opt.base.solvers import OptSolver

if TYPE_CHECKING:
    from .water import WaterStateData


class LinearWater:
    def build(self, block: BlockData, state: "WaterStateData") -> None:
        p = state.params
        dT = state.temperature - p.temperature_ref
        dP = state.pressure - p.pressure_ref
        block.enthalpy = Constraint(
            expr=state.enth_mass == p.enthalpy_ref + p.cp_ref * dT + dP / p.density_ref
        )
        block.entropy = Constraint(
            expr=state.entr_mass
            == p.entropy_ref
            + (p.cp_ref / p.temperature_ref) * dT
            - (p.expansion_ref / p.density_ref) * dP
        )
        block.density = Constraint(
            expr=state.dens_mass
            == p.density_ref * (1 - p.expansion_ref * dT + p.compressibility_ref * dP)
        )
        block.heat_capacity = Constraint(expr=state.cp_mass == p.cp_ref)

    def initialize(
        self,
        block: BlockData,
        state: "WaterStateData",
        *,
        model: BlockData,
        solver: OptSolver,
    ) -> SolverResults:
        return solver.solve(model)
