"""A countercurrent 1D exchanger discretized by finite-volume balances."""

from pyomo.core.base.block import BlockData
from pyomo.environ import Block, Constraint, Expression, RangeSet, Var, value
from pyomo.opt import SolverResults
from pyomo.opt.base.solvers import OptSolver

from .interface import SharedHX
from ..streams import convert, interpolate, states, stream_balance


class DistributedHX:
    def __init__(self, finite_elements: int = 10) -> None:
        if (
            isinstance(finite_elements, bool)
            or not isinstance(finite_elements, int)
            or finite_elements < 1
        ):
            raise ValueError("finite_elements must be a positive integer")
        self.finite_elements = finite_elements

    def build(self, block: BlockData, shared: SharedHX) -> None:
        n = self.finite_elements
        block.cells = RangeSet(0, n - 1)
        block.interior = RangeSet(1, n - 1)
        t0 = shared.time.first()
        block.hot_states = states(
            shared.hot_inlet[t0].params, shared.time, block.interior
        )
        block.cold_states = states(
            shared.cold_inlet[t0].params, shared.time, block.interior
        )
        power = shared.hot_inlet[t0].params.get_metadata().get_derived_units("power")
        block.cell_duty = Var(
            shared.time, block.cells, initialize=1000 / n, units=power
        )
        block.cell_length = Expression(expr=shared.length / n)
        block.hot = Block(shared.time, block.cells)
        block.cold = Block(shared.time, block.cells)

        def hot(t, x):
            if x == 0:
                return shared.hot_inlet[t]
            if x == n:
                return shared.hot_outlet[t]
            return block.hot_states[t, x]

        def cold(t, x):
            if x == 0:
                return shared.cold_outlet[t]
            if x == n:
                return shared.cold_inlet[t]
            return block.cold_states[t, x]

        for t in shared.time:
            for x in block.cells:
                stream_balance(
                    block.hot[t, x],
                    hot(t, x),
                    hot(t, x + 1),
                    -block.cell_duty[t, x],
                    pressure_drop=shared.hot_pressure_drop[t] / n,
                )
                stream_balance(
                    block.cold[t, x],
                    cold(t, x + 1),
                    cold(t, x),
                    block.cell_duty[t, x],
                    pressure_drop=shared.cold_pressure_drop[t] / n,
                )

        def heat_transfer(b, t, x):
            temperature = hot(t, x).temperature
            driving_force = (
                hot(t, x).temperature
                + hot(t, x + 1).temperature
                - convert(cold(t, x).temperature, temperature)
                - convert(cold(t, x + 1).temperature, temperature)
            ) / 2
            return (
                b.cell_duty[t, x]
                == shared.U[t]
                * (shared.area / shared.length)
                * b.cell_length
                * driving_force
            )

        block.heat_transfer = Constraint(shared.time, block.cells, rule=heat_transfer)

    def initialize(
        self,
        block: BlockData,
        shared: SharedHX,
        *,
        model: BlockData,
        solver: OptSolver,
    ) -> SolverResults:
        n = self.finite_elements
        for t in shared.time:
            for x in block.interior:
                interpolate(
                    block.hot_states[t, x],
                    shared.hot_inlet[t],
                    shared.hot_outlet[t],
                    x / n,
                )
                interpolate(
                    block.cold_states[t, x],
                    shared.cold_outlet[t],
                    shared.cold_inlet[t],
                    x / n,
                )
            duty_guess = value(shared.heat_duty[t], exception=False)
            if duty_guess is None:
                temperature = shared.hot_inlet[t].temperature
                duty_guess = (
                    value(
                        shared.U[t]
                        * shared.area
                        * (
                            temperature
                            - convert(shared.cold_inlet[t].temperature, temperature)
                        )
                    )
                    / 4
                )
            for x in block.cells:
                block.cell_duty[t, x].set_value(duty_guess / n)
        return solver.solve(model)
