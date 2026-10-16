"""Steady liquid pump: common mass/energy balances and fixed efficiency."""

from idaes.core import UnitModelBlockData, declare_process_block_class
from idaes.core.util.config import is_physical_parameter_block
from pyomo.common.config import ConfigValue
from pyomo.environ import Block, Constraint, Expression, Var, units as u

from ..streams import add_stream_ports, stream_balance


@declare_process_block_class("Pump")
class PumpData(UnitModelBlockData):
    CONFIG = UnitModelBlockData.CONFIG()
    CONFIG.declare("property_package", ConfigValue(domain=is_physical_parameter_block))

    def build(self) -> None:
        super().build()
        if self.config.dynamic or self.config.has_holdup:
            raise ValueError("Only steady-state operation without holdup is supported")
        add_stream_ports(self, self.config.property_package)
        time = self.flowsheet().time
        self.efficiency = Var(initialize=0.7, bounds=(1e-6, 1))
        self.work = Var(time, initialize=200, bounds=(0, None), units=u.W)
        self.pressure_rise = Expression(
            time,
            rule=lambda b, t: b.outlet_state[t].pressure - b.inlet_state[t].pressure,
        )
        self.balances = Block(time)
        for t in time:
            stream_balance(
                self.balances[t],
                self.inlet_state[t],
                self.outlet_state[t],
                self.work[t],
                preserve_pressure=False,
            )
        self.fluid_work = Constraint(
            time,
            rule=lambda b, t: (
                b.work[t] * b.efficiency
                == b.pressure_rise[t]
                * b.outlet_state[t].flow_mass
                / b.outlet_state[t].dens_mass
            ),
        )
