"""First-order approximation of the liquid equal-percentage pressure-flow law."""

from pyomo.core.base.block import BlockData
from pyomo.environ import Constraint, log
from pyomo.opt import SolverResults
from pyomo.opt.base.solvers import OptSolver

from .interface import SharedValve


class LinearValve:
    def build(self, block: BlockData, shared: SharedValve) -> None:
        def pressure_flow(b, t):
            return shared.inlet[t].flow_mass == shared.nominal_flow * (
                1
                + (shared.Cv - shared.nominal_Cv) / shared.nominal_Cv
                + (shared.pressure_drop[t] - shared.nominal_pressure_drop)
                / (2 * shared.nominal_pressure_drop)
                + (shared.inlet[t].dens_mass - shared.nominal_density)
                / (2 * shared.nominal_density)
                + log(shared.alpha) * (shared.opening[t] - shared.nominal_opening)
            )

        block.pressure_flow = Constraint(shared.time, rule=pressure_flow)

    def initialize(
        self,
        block: BlockData,
        shared: SharedValve,
        *,
        model: BlockData,
        solver: OptSolver,
    ) -> SolverResults:
        return solver.solve(model)
