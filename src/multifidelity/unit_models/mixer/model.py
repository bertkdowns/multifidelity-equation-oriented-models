"""Two-inlet adiabatic mixer; outlet pressure follows the main inlet.

The second inlet is admitted at the main pressure without changing enthalpy
(an implicit makeup letdown). No pressure equality is imposed on that inlet.
"""

from idaes.core import UnitModelBlockData, declare_process_block_class
from pyomo.common.config import ConfigValue
from pyomo.environ import Constraint

from ..streams import states


@declare_process_block_class("Mixer")
class MixerData(UnitModelBlockData):
    CONFIG = UnitModelBlockData.CONFIG()
    CONFIG.declare("property_package", ConfigValue())

    def build(self):
        super().build()
        time = self.flowsheet().time
        for name in ("main", "makeup", "outlet"):
            state = states(self.config.property_package, time, inlet=name != "outlet")
            self.add_component(name + "_state", state)
            self.add_port(name, state)
        self.material = Constraint(
            time,
            rule=lambda b, t: (
                b.outlet_state[t].flow_mass
                == b.main_state[t].flow_mass + b.makeup_state[t].flow_mass
            ),
        )
        self.energy = Constraint(
            time,
            rule=lambda b, t: (
                b.outlet_state[t].flow_mass * b.outlet_state[t].enth_mass
                == b.main_state[t].flow_mass * b.main_state[t].enth_mass
                + b.makeup_state[t].flow_mass * b.makeup_state[t].enth_mass
            ),
        )
        self.pressure = Constraint(
            time,
            rule=lambda b, t: b.outlet_state[t].pressure == b.main_state[t].pressure,
        )
