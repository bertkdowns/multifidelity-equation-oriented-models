"""A countercurrent 1D exchanger discretized by finite-volume balances."""

from typing import TYPE_CHECKING

from pyomo.core.base.block import BlockData
from pyomo.environ import Block, Constraint, Expression, RangeSet, Var, value
from pyomo.opt import SolverResults
from pyomo.opt.base.solvers import OptSolver

if TYPE_CHECKING:
    from .model import HeatExchangerData
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

    def build(self, block: BlockData, hx: "HeatExchangerData") -> None:
        time = hx.flowsheet().time
        n = self.finite_elements
        block.cells = RangeSet(0, n - 1)
        block.interior = RangeSet(1, n - 1)
        t0 = time.first()
        block.hot_states = states(hx.hot_inlet_state[t0].params, time, block.interior)
        block.cold_states = states(hx.cold_inlet_state[t0].params, time, block.interior)
        power = hx.hot_inlet_state[t0].params.get_metadata().get_derived_units("power")
        block.cell_duty = Var(time, block.cells, initialize=1000 / n, units=power)
        block.cell_length = Expression(expr=hx.length / n)
        block.hot = Block(time, block.cells)
        block.cold = Block(time, block.cells)

        def hot(t, x):
            if x == 0:
                return hx.hot_inlet_state[t]
            if x == n:
                return hx.hot_outlet_state[t]
            return block.hot_states[t, x]

        def cold(t, x):
            if x == 0:
                return hx.cold_outlet_state[t]
            if x == n:
                return hx.cold_inlet_state[t]
            return block.cold_states[t, x]

        for t in time:
            for x in block.cells:
                stream_balance(
                    block.hot[t, x],
                    hot(t, x),
                    hot(t, x + 1),
                    -block.cell_duty[t, x],
                    pressure_drop=hx.hot_pressure_drop[t] / n,
                )
                stream_balance(
                    block.cold[t, x],
                    cold(t, x + 1),
                    cold(t, x),
                    block.cell_duty[t, x],
                    pressure_drop=hx.cold_pressure_drop[t] / n,
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
                == hx.U[t] * (hx.area / hx.length) * b.cell_length * driving_force
            )

        block.heat_transfer = Constraint(time, block.cells, rule=heat_transfer)

    def initialize(
        self,
        block: BlockData,
        hx: "HeatExchangerData",
        *,
        model: BlockData,
        solver: OptSolver,
    ) -> SolverResults:
        time = hx.flowsheet().time
        n = self.finite_elements
        for t in time:
            for x in block.interior:
                interpolate(
                    block.hot_states[t, x],
                    hx.hot_inlet_state[t],
                    hx.hot_outlet_state[t],
                    x / n,
                )
                interpolate(
                    block.cold_states[t, x],
                    hx.cold_outlet_state[t],
                    hx.cold_inlet_state[t],
                    x / n,
                )
            duty_guess = value(hx.heat_duty[t], exception=False)
            if duty_guess is None:
                temperature = hx.hot_inlet_state[t].temperature
                duty_guess = (
                    value(
                        hx.U[t]
                        * hx.area
                        * (
                            temperature
                            - convert(hx.cold_inlet_state[t].temperature, temperature)
                        )
                    )
                    / 4
                )
            for x in block.cells:
                block.cell_duty[t, x].set_value(duty_guess / n)
        return solver.solve(model)
