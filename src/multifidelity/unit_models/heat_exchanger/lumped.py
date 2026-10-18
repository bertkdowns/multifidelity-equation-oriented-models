"""Countercurrent lumped exchanger with a logarithmic mean driving force."""

from typing import TYPE_CHECKING

from pyomo.core.base.block import BlockData
from pyomo.environ import Block, Constraint, Expression, log, sqrt
from pyomo.opt import SolverResults
from pyomo.opt.base.solvers import OptSolver

if TYPE_CHECKING:
    from .model import HeatExchangerData
from ..streams import convert, stream_balance


class LumpedHX:
    def build(self, block: BlockData, hx: "HeatExchangerData") -> None:
        time = hx.flowsheet().time
        block.hot = Block(time)
        block.cold = Block(time)
        for t in time:
            stream_balance(
                block.hot[t],
                hx.hot_inlet_state[t],
                hx.hot_outlet_state[t],
                -hx.heat_duty[t],
                pressure_drop=hx.hot_pressure_drop[t],
            )
            # Duty is already defined by the parent cold-stream enthalpy change.
            # Add only material/pressure balances here to avoid a duplicate equation.
            stream_balance(
                block.cold[t],
                hx.cold_inlet_state[t],
                hx.cold_outlet_state[t],
                pressure_drop=hx.cold_pressure_drop[t],
            )

        block.delta_in = Expression(
            time,
            rule=lambda b, t: (
                hx.hot_inlet_state[t].temperature
                - convert(
                    hx.cold_outlet_state[t].temperature,
                    hx.hot_inlet_state[t].temperature,
                )
            ),
        )
        block.delta_out = Expression(
            time,
            rule=lambda b, t: (
                hx.hot_outlet_state[t].temperature
                - convert(
                    hx.cold_inlet_state[t].temperature,
                    hx.hot_outlet_state[t].temperature,
                )
            ),
        )

        # Smooth log mean used by IDAES (Kazi et al., 2020); finite at equal
        # terminal differences. Both terminal differences must have the same sign.
        def log_mean(b, t):
            ratio = b.delta_out[t] / b.delta_in[t]
            return (
                b.delta_in[t]
                * sqrt((ratio - 1) ** 2 + 1e-10)
                / sqrt(log(ratio) ** 2 + 1e-10)
            )

        block.delta_temperature = Expression(time, rule=log_mean)
        block.heat_transfer = Constraint(
            time,
            rule=lambda b, t: (
                hx.heat_duty[t] == hx.U[t] * hx.area * b.delta_temperature[t]
            ),
        )

    def initialize(
        self,
        block: BlockData,
        hx: "HeatExchangerData",
        *,
        model: BlockData,
        solver: OptSolver,
    ) -> SolverResults:
        return solver.solve(model)
