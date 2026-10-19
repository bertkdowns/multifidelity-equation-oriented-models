"""Aggregate heating-COP relation, without an internal refrigerant cycle."""

from typing import TYPE_CHECKING

from pyomo.environ import Block, Constraint, Var, units as u

from ..streams import stream_balance

if TYPE_CHECKING:
    from .model import HeatPumpData


class COPHeatPump:
    def build(self, block, hp: "HeatPumpData") -> None:
        time = hp.flowsheet().time
        block.COP = Var(time, initialize=3, bounds=(1, None), units=u.dimensionless)
        block.source = Block(time)
        block.sink = Block(time)
        for t in time:
            stream_balance(
                block.source[t], hp.source_inlet_state[t], hp.source_outlet_state[t],
                -hp.cooling_duty[t],
            )
            # Heating duty is defined from the sink enthalpy gain by the parent.
            stream_balance(
                block.sink[t], hp.sink_inlet_state[t], hp.sink_outlet_state[t],
            )
        block.performance = Constraint(
            time, rule=lambda b, t: hp.heating_duty[t]
            == b.COP[t] * hp.electrical_power[t],
        )

    def initialize(self, block, hp: "HeatPumpData", *, model, solver):
        return solver.solve(model)
