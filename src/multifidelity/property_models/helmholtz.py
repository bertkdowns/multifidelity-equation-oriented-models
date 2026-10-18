"""Liquid IAPWS-95 properties expressed over the parent water-state variables."""

from typing import TYPE_CHECKING

from idaes.models.properties.general_helmholtz import (
    AmountBasis,
    HelmholtzThermoExpressions,
)
from pyomo.core.base.block import BlockData
from pyomo.environ import Constraint
from pyomo.opt import SolverResults
from pyomo.opt.base.solvers import OptSolver

if TYPE_CHECKING:
    from .water import WaterStateData


class HelmholtzWater:
    def build(self, block: BlockData, state: "WaterStateData") -> None:
        thermo = HelmholtzThermoExpressions(
            block,
            state.params.get_helmholtz_parameters(),
            amount_basis=AmountBasis.MASS,
        )
        inputs = {"T": state.temperature, "p": state.pressure}
        block.enthalpy = Constraint(expr=state.enth_mass == thermo.h_liq(**inputs))
        block.entropy = Constraint(expr=state.entr_mass == thermo.s_liq(**inputs))
        block.density = Constraint(expr=state.dens_mass == thermo.rho_liq(**inputs))
        block.heat_capacity = Constraint(expr=state.cp_mass == thermo.cp_liq(**inputs))

    def initialize(
        self,
        block: BlockData,
        state: "WaterStateData",
        *,
        model: BlockData,
        solver: OptSolver,
    ) -> SolverResults:
        return solver.solve(model)
