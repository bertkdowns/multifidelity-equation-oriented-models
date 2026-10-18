"""Shutoff-capable hydraulic fallback calibrated at one operating point."""

from typing import TYPE_CHECKING

from pyomo.core.base.block import BlockData
from pyomo.environ import Constraint
from pyomo.opt import SolverResults
from pyomo.opt.base.solvers import OptSolver

if TYPE_CHECKING:
    from .model import ValveData


class BasicValve:
    def build(self, block: BlockData, valve: "ValveData") -> None:
        block.pressure_flow = Constraint(
            valve.flowsheet().time, rule=lambda b, t: valve.basic_residual[t] == 0
        )

    def initialize(
        self,
        block: BlockData,
        valve: "ValveData",
        *,
        model: BlockData,
        solver: OptSolver,
    ) -> SolverResults:
        return solver.solve(model)
