"""Normalized, unchoked compressible valve approximation.

Pressure-squared dependence with an inlet-temperature correction; not a
manufacturer steam-valve/choked-flow correlation. Reference data calibrate its
coefficient, avoiding a claim that a liquid Cv directly predicts steam flow.
"""

from typing import TYPE_CHECKING

from pyomo.core.base.block import BlockData
from pyomo.environ import Constraint, Param
from pyomo.environ import units as u

from .pressure_flow import PressureFlowValve

if TYPE_CHECKING:
    from .model import ValveData


class VaporPressureFlowValve(PressureFlowValve):
    def __init__(
        self, *, inlet_pressure: float, outlet_pressure: float, temperature: float
    ) -> None:
        self.inlet_pressure = inlet_pressure
        self.outlet_pressure = outlet_pressure
        self.temperature = temperature

    def build(self, block: BlockData, valve: "ValveData") -> None:
        block.pressure_squared_ref = Param(
            initialize=self.inlet_pressure**2 - self.outlet_pressure**2, units=u.Pa**2
        )
        block.temperature_ref = Param(initialize=self.temperature, units=u.K)
        block.residual = Constraint(
            valve.flowsheet().time,
            rule=lambda b, t: (
                (valve.inlet_state[t].flow_mass / valve.nominal_flow) ** 2
                == (valve.Cv / valve.nominal_Cv) ** 2
                * (valve.opening[t] / valve.nominal_opening) ** 2
                * (
                    valve.inlet_state[t].pressure ** 2
                    - valve.outlet_state[t].pressure ** 2
                )
                / b.pressure_squared_ref
                * b.temperature_ref
                / valve.inlet_state[t].temperature
            ),
        )
