"""First-order approximation of the liquid equal-percentage pressure-flow law."""

from typing import TYPE_CHECKING

from pyomo.core.base.block import BlockData
from pyomo.environ import Constraint, log
from pyomo.opt import SolverResults
from pyomo.opt.base.solvers import OptSolver

if TYPE_CHECKING:
    from .model import ValveData


class LinearValve:
    def build(self, block: BlockData, valve: "ValveData") -> None:
        def pressure_flow(b, t):
            return valve.inlet_state[t].flow_mass == valve.nominal_flow * (
                1
                + (valve.Cv - valve.nominal_Cv) / valve.nominal_Cv
                + (valve.pressure_drop[t] - valve.nominal_pressure_drop)
                / (2 * valve.nominal_pressure_drop)
                + (valve.inlet_state[t].dens_mass - valve.nominal_density)
                / (2 * valve.nominal_density)
                + (
                    1 / valve.nominal_opening
                    if valve.config.characteristic == "linear"
                    else log(valve.alpha)
                )
                * (valve.opening[t] - valve.nominal_opening)
            )

        block.pressure_flow = Constraint(valve.flowsheet().time, rule=pressure_flow)

    def initialize(
        self,
        block: BlockData,
        valve: "ValveData",
        *,
        model: BlockData,
        solver: OptSolver,
    ) -> SolverResults:
        return solver.solve(model)
