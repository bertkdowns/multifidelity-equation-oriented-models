"""Three-stream milk effect with aggregate or explicit MVR heat recovery."""

from idaes.core import StateBlockData, UnitModelBlockData, declare_process_block_class
import idaes.logger as idaeslog
from idaes.core.solvers import get_solver
from idaes.core.util.config import is_physical_parameter_block
from idaes.core.util.exceptions import InitializationError
from pyomo.common.config import ConfigValue
from pyomo.environ import (
    Block,
    Constraint,
    Expression,
    Var,
    check_optimal_termination,
    units as u,
)

from ...base import MultiFidelityMixin, fixed_inputs
from ..streams import enthalpy_flow
from .aggregate import AggregateMilkEvaporator
from .detailed import DetailedMilkEvaporator


def component_flow(state, component):
    return sum(
        state.get_material_flow_terms(p, component)
        for p in state.phase_list
        if (p, component) in state.phase_component_set
    )


@declare_process_block_class("MilkEvaporator")
class MilkEvaporatorData(MultiFidelityMixin["MilkEvaporatorData"], UnitModelBlockData):
    CONFIG = UnitModelBlockData.CONFIG()
    CONFIG.declare(
        "milk_property_package", ConfigValue(domain=is_physical_parameter_block)
    )
    CONFIG.declare(
        "water_property_package", ConfigValue(domain=is_physical_parameter_block)
    )
    CONFIG.declare("fidelities", ConfigValue(default=None))

    def build(self):
        super().build()
        if self.config.dynamic or self.config.has_holdup:
            raise ValueError("Only steady-state operation without holdup is supported")
        time = self.flowsheet().time
        for name, package in (
            ("milk_inlet", self.config.milk_property_package),
            ("milk_outlet", self.config.milk_property_package),
            ("water_outlet", self.config.water_property_package),
        ):
            state = package.build_state_block(
                time,
                defined_state=name == "milk_inlet",
                has_phase_equilibrium=True,
            )
            self.add_component(name + "_state", state)
            self.add_port(name, state)
        self.mvr_power = Var(time, initialize=1000, bounds=(0, None), units=u.W)
        self.operating_pressure = Var(
            time, initialize=60000, bounds=(10000, None), units=u.Pa
        )
        self.heat_duty = Var(time, initialize=10000, bounds=(0, None), units=u.W)
        self.recompressed_enthalpy = Var(time, initialize=48000, units=u.J / u.mol)
        self.heat_recovery_effectiveness = Var(
            time,
            initialize=0.75,
            bounds=(0, 1),
            units=u.dimensionless,
        )
        self.heat_recovery = Constraint(
            time,
            rule=lambda b, t: (
                b.heat_duty[t]
                == b.heat_recovery_effectiveness[t]
                * b.water_outlet_state[t].flow_mol
                * (
                    b.recompressed_enthalpy[t]
                    - b.water_outlet_state[t].enth_mol_sat_phase["Liq"]
                )
            ),
        )
        self.water_removal_rate = Expression(
            time,
            rule=lambda b, t: b.water_outlet_state[t].flow_mass,
        )
        self.product_solids_mass_fraction = Expression(
            time,
            rule=lambda b, t: (
                b.milk_outlet_state[t].mole_frac_comp["milk_solid"]
                * b.config.milk_property_package.get_component("milk_solid").mw
                / b.milk_outlet_state[t].mw
            ),
        )
        self.energy_residual = Expression(
            time,
            rule=lambda b, t: (
                enthalpy_flow(b.milk_inlet_state[t])
                + b.mvr_power[t]
                - enthalpy_flow(b.milk_outlet_state[t])
                - enthalpy_flow(b.water_outlet_state[t])
            ),
        )
        self.component_residual = Expression(
            time,
            self.config.milk_property_package.component_list,
            rule=lambda b, t, j: (
                component_flow(b.milk_inlet_state[t], j)
                - component_flow(b.milk_outlet_state[t], j)
                - (
                    component_flow(b.water_outlet_state[t], j)
                    if j == "water"
                    else 0 * u.mol / u.s
                )
            ),
        )
        self.build_fidelities(
            self.config.fidelities
            if self.config.fidelities is not None
            else {
                "low": AggregateMilkEvaporator(),
                "high": DetailedMilkEvaporator(),
            },
            self,
        )

    def initialize_build(self, *, solver=None, optarg=None):
        solver = (
            get_solver(solver, optarg)
            if solver is None or isinstance(solver, str)
            else solver
        )
        inputs = []
        for variable in self.milk_inlet.vars.values():
            inputs.extend(variable.values())
        flags = [(v, v.fixed) for v in self.component_data_objects(Var, active=None)]
        try:
            with fixed_inputs(inputs):
                name = self.active_fidelity
                # Use the property package's existing bubble-point/PH initializer.
                seen = set()
                for state in self.component_data_objects(Block, active=True):
                    if (
                        isinstance(state, StateBlockData)
                        and state.params is self.config.milk_property_package
                    ):
                        states = state.parent_component()
                        if id(states) not in seen:
                            seen.add(id(states))
                            states.initialize(
                                solver=solver.name,
                                optarg=dict(solver.options),
                                outlvl=idaeslog.WARNING,
                            )
                result = self._builders[name].initialize(
                    self.fidelities[name],
                    self,
                    model=self,
                    solver=solver,
                )
                if not check_optimal_termination(result):
                    raise InitializationError(
                        f"{self.name}: {name} initialization failed"
                    )
        finally:
            # Third-party state initializers may fail before releasing fixations.
            for variable, fixed in flags:
                variable.fix() if fixed else variable.unfix()
        return result
