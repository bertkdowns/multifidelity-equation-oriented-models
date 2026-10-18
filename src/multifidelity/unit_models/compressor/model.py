"""Adiabatic compressor with a constant isentropic efficiency."""

from idaes.core import UnitModelBlockData, declare_process_block_class
from idaes.models.properties.general_helmholtz import (
    AmountBasis,
    HelmholtzThermoExpressions,
)
from pyomo.common.config import ConfigValue
from pyomo.environ import Block, Constraint, Expression, Var, units as u

from ..streams import add_stream_ports, stream_balance


@declare_process_block_class("Compressor")
class CompressorData(UnitModelBlockData):
    CONFIG = UnitModelBlockData.CONFIG()
    CONFIG.declare("property_package", ConfigValue())

    def build(self):
        super().build()
        add_stream_ports(self, self.config.property_package)
        time = self.flowsheet().time
        self.efficiency = Var(initialize=0.7, bounds=(0.01, 1))
        self.work = Var(time, initialize=13000, bounds=(0, None), units=u.W)
        self.balances = Block(time)
        thermo = HelmholtzThermoExpressions(
            self, self.config.property_package, amount_basis=AmountBasis.MASS
        )
        self.isentropic_enthalpy = Expression(
            time,
            rule=lambda b, t: thermo.h(
                s=b.inlet_state[t].entr_mass, p=b.outlet_state[t].pressure
            ),
        )
        for t in time:
            stream_balance(
                self.balances[t],
                self.inlet_state[t],
                self.outlet_state[t],
                self.work[t],
                preserve_pressure=False,
            )
        self.isentropic = Constraint(
            time,
            rule=lambda b, t: (
                b.efficiency
                * (b.outlet_state[t].enth_mass - b.inlet_state[t].enth_mass)
                == b.isentropic_enthalpy[t] - b.inlet_state[t].enth_mass
            ),
        )
