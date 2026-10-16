"""Steady prescribed-duty heater/cooler with zero pressure drop."""

from idaes.core import UnitModelBlockData, declare_process_block_class
from idaes.core.util.config import is_physical_parameter_block
from pyomo.common.config import ConfigValue
from pyomo.environ import Block, Var, units as u

from ..streams import add_stream_ports, stream_balance


@declare_process_block_class("ThermalConditioner")
class ThermalConditionerData(UnitModelBlockData):
    CONFIG = UnitModelBlockData.CONFIG()
    CONFIG.declare("property_package", ConfigValue(domain=is_physical_parameter_block))

    def build(self) -> None:
        super().build()
        if self.config.dynamic or self.config.has_holdup:
            raise ValueError("Only steady-state operation without holdup is supported")
        add_stream_ports(self, self.config.property_package)
        self.heat_duty = Var(self.flowsheet().time, initialize=0, units=u.W)
        self.balances = Block(self.flowsheet().time)
        for t in self.flowsheet().time:
            stream_balance(
                self.balances[t],
                self.inlet_state[t],
                self.outlet_state[t],
                self.heat_duty[t],
            )
