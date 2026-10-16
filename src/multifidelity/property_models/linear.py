"""An affine, constant-cp liquid-water approximation around room temperature."""

from pyomo.core.base.block import BlockData
from pyomo.environ import Constraint
from pyomo.opt import SolverResults
from pyomo.opt.base.solvers import OptSolver

from .interface import SharedWater


class LinearWater:
    def build(self, block: BlockData, shared: SharedWater) -> None:
        p = shared.parameters
        dT = shared.temperature - p.temperature_ref
        dP = shared.pressure - p.pressure_ref
        block.enthalpy = Constraint(
            expr=shared.enth_mass == p.enthalpy_ref + p.cp_ref * dT + dP / p.density_ref
        )
        block.entropy = Constraint(
            expr=shared.entr_mass
            == p.entropy_ref
            + (p.cp_ref / p.temperature_ref) * dT
            - (p.expansion_ref / p.density_ref) * dP
        )
        block.density = Constraint(
            expr=shared.dens_mass
            == p.density_ref * (1 - p.expansion_ref * dT + p.compressibility_ref * dP)
        )
        block.heat_capacity = Constraint(expr=shared.cp_mass == p.cp_ref)

    def initialize(
        self,
        block: BlockData,
        shared: SharedWater,
        *,
        model: BlockData,
        solver: OptSolver,
    ) -> SolverResults:
        return solver.solve(model)
