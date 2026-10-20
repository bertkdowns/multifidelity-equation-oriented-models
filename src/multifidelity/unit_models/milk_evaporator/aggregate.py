"""Overall balances with affine outlet closures and heat-recovery effectiveness."""

from idaes.models.properties.general_helmholtz import (
    AmountBasis,
    HelmholtzThermoExpressions,
)
from pyomo.environ import Constraint, Expression, Param, units as u

from ..streams import enthalpy_flow


class AggregateMilkEvaporator:
    def build(self, block, effect):
        time = effect.flowsheet().time
        # Correlations are local assumptions supplied/calibrated by the caller.
        block.reference_feed_enthalpy = Param(
            initialize=15000, mutable=True, units=u.J / u.mol
        )
        block.reference_specific_work = Param(
            initialize=800, mutable=True, units=u.J / u.mol
        )
        block.reference_pressure = Param(initialize=60000, mutable=True, units=u.Pa)
        block.reference_effectiveness = Param(initialize=0.75, mutable=True)
        block.product_enthalpy_reference = Param(
            initialize=9000, mutable=True, units=u.J / u.mol
        )
        block.product_enthalpy_feed_slope = Param(initialize=0, mutable=True)
        block.product_enthalpy_work_slope = Param(initialize=0, mutable=True)
        block.product_enthalpy_pressure_slope = Param(
            initialize=0, mutable=True, units=u.J / u.mol / u.Pa
        )
        block.product_enthalpy_effectiveness_slope = Param(
            initialize=0, mutable=True, units=u.J / u.mol
        )
        block.water_pressure_reference = Param(
            initialize=80000, mutable=True, units=u.Pa
        )
        block.water_pressure_feed_slope = Param(
            initialize=0, mutable=True, units=u.Pa * u.mol / u.J
        )
        block.water_pressure_work_slope = Param(
            initialize=0, mutable=True, units=u.Pa * u.mol / u.J
        )
        block.water_pressure_operating_slope = Param(initialize=1, mutable=True)
        block.water_pressure_effectiveness_slope = Param(
            initialize=0, mutable=True, units=u.Pa
        )
        thermo = HelmholtzThermoExpressions(
            block,
            effect.config.water_property_package,
            amount_basis=AmountBasis.MOLE,
        )
        block.vapor_enthalpy = Expression(
            time,
            rule=lambda b, t: thermo.h(p=effect.operating_pressure[t], x=1),
        )
        block.specific_work = Expression(
            time,
            rule=lambda b, t: effect.mvr_power[t] / effect.milk_inlet_state[t].flow_mol,
        )
        block.product_enthalpy = Constraint(
            time,
            rule=lambda b, t: (
                effect.milk_outlet_state[t].enth_mol
                == b.product_enthalpy_reference
                + b.product_enthalpy_feed_slope
                * (effect.milk_inlet_state[t].enth_mol - b.reference_feed_enthalpy)
                + b.product_enthalpy_work_slope
                * (b.specific_work[t] - b.reference_specific_work)
                + b.product_enthalpy_pressure_slope
                * (effect.operating_pressure[t] - b.reference_pressure)
                + b.product_enthalpy_effectiveness_slope
                * (effect.heat_recovery_effectiveness[t] - b.reference_effectiveness)
            ),
        )
        block.water_pressure = Constraint(
            time,
            rule=lambda b, t: (
                effect.water_outlet_state[t].pressure
                == b.water_pressure_reference
                + b.water_pressure_feed_slope
                * (effect.milk_inlet_state[t].enth_mol - b.reference_feed_enthalpy)
                + b.water_pressure_work_slope
                * (b.specific_work[t] - b.reference_specific_work)
                + b.water_pressure_operating_slope
                * (effect.operating_pressure[t] - b.reference_pressure)
                + b.water_pressure_effectiveness_slope
                * (effect.heat_recovery_effectiveness[t] - b.reference_effectiveness)
            ),
        )
        block.product_pressure = Constraint(
            time,
            rule=lambda b, t: (
                effect.milk_outlet_state[t].pressure == effect.operating_pressure[t]
            ),
        )
        block.material = Constraint(
            time,
            effect.config.milk_property_package.component_list,
            rule=lambda b, t, j: effect.component_residual[t, j] == 0,
        )
        block.energy = Constraint(
            time, rule=lambda b, t: effect.energy_residual[t] == 0
        )
        block.compression = Constraint(
            time,
            rule=lambda b, t: (
                effect.water_outlet_state[t].flow_mol
                * (effect.recompressed_enthalpy[t] - b.vapor_enthalpy[t])
                == effect.mvr_power[t]
            ),
        )
        block.water_energy = Constraint(
            time,
            rule=lambda b, t: (
                enthalpy_flow(effect.water_outlet_state[t])
                == effect.water_outlet_state[t].flow_mol
                * effect.recompressed_enthalpy[t]
                - effect.heat_duty[t]
            ),
        )

    def initialize(self, block, effect, *, model, solver):
        return solver.solve(model)
