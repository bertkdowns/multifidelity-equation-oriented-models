"""Shutoff-capable hydraulic fallback calibrated at one operating point."""

from pyomo.core.base.block import BlockData
from pyomo.environ import Constraint
from pyomo.opt import SolverResults
from pyomo.opt.base.solvers import OptSolver

from .interface import SharedValve


class BasicValve:
    def build(self, block: BlockData, shared: SharedValve) -> None:
        block.pressure_flow = Constraint(
            shared.time, rule=lambda b, t: shared.basic_residual[t] == 0
        )

    def initialize(
        self,
        block: BlockData,
        shared: SharedValve,
        *,
        model: BlockData,
        solver: OptSolver,
    ) -> SolverResults:
        return solver.solve(model)
