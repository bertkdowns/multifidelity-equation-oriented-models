"""Two-way homogeneous splitter with a shared pressure and enthalpy."""

from idaes.core import UnitModelBlockData, declare_process_block_class
from pyomo.common.config import ConfigValue
from pyomo.environ import Constraint, Var

from ..streams import states


@declare_process_block_class("Splitter")
class SplitterData(UnitModelBlockData):
    CONFIG = UnitModelBlockData.CONFIG()
    CONFIG.declare("property_package", ConfigValue())

    def build(self):
        super().build()
        time = self.flowsheet().time
        for name in ("inlet", "main", "branch"):
            state = states(self.config.property_package, time, inlet=name == "inlet")
            self.add_component(name + "_state", state)
            self.add_port(name, state)
        self.fraction = Var(time, initialize=0.97, bounds=(0, 1))
        self.material = Constraint(
            time,
            rule=lambda b, t: (
                b.inlet_state[t].flow_mass
                == b.main_state[t].flow_mass + b.branch_state[t].flow_mass
            ),
        )
        self.split = Constraint(
            time,
            rule=lambda b, t: (
                b.main_state[t].flow_mass == b.fraction[t] * b.inlet_state[t].flow_mass
            ),
        )
        self.pressure = Constraint(
            time,
            ("main", "branch"),
            rule=lambda b, t, n: (
                getattr(b, n + "_state")[t].pressure == b.inlet_state[t].pressure
            ),
        )
        self.enthalpy = Constraint(
            time,
            ("main", "branch"),
            rule=lambda b, t, n: (
                getattr(b, n + "_state")[t].enth_mass == b.inlet_state[t].enth_mass
            ),
        )
