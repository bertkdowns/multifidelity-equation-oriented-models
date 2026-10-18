"""Adiabatic equilibrium flash with specified phase recovery fractions."""

from idaes.core import UnitModelBlockData, declare_process_block_class
from idaes.models.properties.general_helmholtz import (
    AmountBasis,
    HelmholtzThermoExpressions,
)
from pyomo.common.config import ConfigValue
from pyomo.environ import Constraint, Expression, Param

from ..streams import states


@declare_process_block_class("FlashSeparator")
class FlashSeparatorData(UnitModelBlockData):
    CONFIG = UnitModelBlockData.CONFIG()
    CONFIG.declare("property_package", ConfigValue())

    def build(self):
        super().build()
        time = self.flowsheet().time
        for name in ("inlet", "liquid", "vapor"):
            state = states(self.config.property_package, time, inlet=name == "inlet")
            self.add_component(name + "_state", state)
            self.add_port(name, state)
        self.liquid_recovery = Param(initialize=0.999, mutable=True)
        self.vapor_recovery = Param(initialize=0.999, mutable=True)
        th = HelmholtzThermoExpressions(
            self, self.config.property_package, amount_basis=AmountBasis.MASS
        )
        self.h_liq = Expression(
            time, rule=lambda b, t: th.h_liq_sat(p=b.inlet_state[t].pressure)
        )
        self.h_vap = Expression(
            time, rule=lambda b, t: th.h_vap_sat(p=b.inlet_state[t].pressure)
        )
        self.material = Constraint(
            time,
            rule=lambda b, t: (
                b.inlet_state[t].flow_mass
                == b.liquid_state[t].flow_mass + b.vapor_state[t].flow_mass
            ),
        )
        self.liquid_split = Constraint(
            time,
            rule=lambda b, t: (
                b.liquid_state[t].flow_mass
                == b.inlet_state[t].flow_mass
                * (
                    b.liquid_recovery * (1 - b.inlet_state[t].vapor_frac)
                    + (1 - b.vapor_recovery) * b.inlet_state[t].vapor_frac
                )
            ),
        )
        self.energy = Constraint(
            time,
            rule=lambda b, t: (
                b.inlet_state[t].flow_mass * b.inlet_state[t].enth_mass
                == b.liquid_state[t].flow_mass * b.liquid_state[t].enth_mass
                + b.vapor_state[t].flow_mass * b.vapor_state[t].enth_mass
            ),
        )
        self.liquid_energy = Constraint(
            time,
            rule=lambda b, t: (
                b.liquid_state[t].flow_mass * b.liquid_state[t].enth_mass
                == b.inlet_state[t].flow_mass
                * (
                    b.liquid_recovery * (1 - b.inlet_state[t].vapor_frac) * b.h_liq[t]
                    + (1 - b.vapor_recovery) * b.inlet_state[t].vapor_frac * b.h_vap[t]
                )
            ),
        )
        self.pressure = Constraint(
            time,
            ("liquid", "vapor"),
            rule=lambda b, t, n: (
                getattr(b, n + "_state")[t].pressure == b.inlet_state[t].pressure
            ),
        )
