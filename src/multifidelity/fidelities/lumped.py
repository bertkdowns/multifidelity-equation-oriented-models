"""Countercurrent lumped exchanger with a logarithmic mean driving force."""

from pyomo.environ import Block, Constraint, Expression, log, sqrt

from ..properties import convert, stream_balance


class LumpedHX:
    def build(self, block, shared):
        block.hot = Block(shared.time)
        block.cold = Block(shared.time)
        for t in shared.time:
            stream_balance(
                block.hot[t],
                shared.hot_inlet[t],
                shared.hot_outlet[t],
                -shared.heat_duty[t],
            )
            # Duty is already defined by the parent cold-stream enthalpy change.
            # Add only material/pressure balances here to avoid a duplicate equation.
            stream_balance(block.cold[t], shared.cold_inlet[t], shared.cold_outlet[t])

        block.delta_in = Expression(
            shared.time,
            rule=lambda b, t: (
                shared.hot_inlet[t].temperature
                - convert(
                    shared.cold_outlet[t].temperature, shared.hot_inlet[t].temperature
                )
            ),
        )
        block.delta_out = Expression(
            shared.time,
            rule=lambda b, t: (
                shared.hot_outlet[t].temperature
                - convert(
                    shared.cold_inlet[t].temperature, shared.hot_outlet[t].temperature
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

        block.delta_temperature = Expression(shared.time, rule=log_mean)
        block.heat_transfer = Constraint(
            shared.time,
            rule=lambda b, t: (
                shared.heat_duty[t]
                == shared.U[t] * shared.area * b.delta_temperature[t]
            ),
        )

    def initialize(self, block, shared, *, solver):
        return solver.solve(block.parent_block())
