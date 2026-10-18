"""Normalized, unchoked compressible valve approximation.

Pressure-squared dependence with an inlet-temperature correction; not a
manufacturer steam-valve/choked-flow correlation. Reference data calibrate its
coefficient, avoiding a claim that a liquid Cv directly predicts steam flow.
"""

from pyomo.core.base.block import BlockData
from pyomo.environ import Constraint, Param, units as u

from .pressure_flow import PressureFlowValve
from .interface import SharedValve


class VaporPressureFlowValve(PressureFlowValve):
    def __init__(
        self, *, inlet_pressure: float, outlet_pressure: float, temperature: float
    ) -> None:
        self.inlet_pressure = inlet_pressure
        self.outlet_pressure = outlet_pressure
        self.temperature = temperature

    def build(self, block: BlockData, shared: SharedValve) -> None:
        block.pressure_squared_ref = Param(
            initialize=self.inlet_pressure**2 - self.outlet_pressure**2, units=u.Pa**2
        )
        block.temperature_ref = Param(initialize=self.temperature, units=u.K)
        block.residual = Constraint(
            shared.time,
            rule=lambda b, t: (
                (shared.inlet[t].flow_mass / shared.nominal_flow) ** 2
                == (shared.Cv / shared.nominal_Cv) ** 2
                * (shared.opening[t] / shared.nominal_opening) ** 2
                * (shared.inlet[t].pressure ** 2 - shared.outlet[t].pressure ** 2)
                / b.pressure_squared_ref
                * b.temperature_ref
                / shared.inlet[t].temperature
            ),
        )
