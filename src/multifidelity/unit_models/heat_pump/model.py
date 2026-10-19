"""Steady heat-pump boundary interface shared by its representations."""

from idaes.core import UnitModelBlockData, declare_process_block_class
from idaes.core.solvers import get_solver
from idaes.core.util.config import is_physical_parameter_block
from idaes.core.util.exceptions import InitializationError
from pyomo.common.config import ConfigValue
from pyomo.environ import Expression, Var, check_optimal_termination

from ...base import MultiFidelityMixin, fixed_inputs
from ..streams import convert, enthalpy_flow, states
from .cop import COPHeatPump


@declare_process_block_class("HeatPump")
class HeatPumpData(MultiFidelityMixin["HeatPumpData"], UnitModelBlockData):
    CONFIG = UnitModelBlockData.CONFIG()
    CONFIG.declare("source_property_package", ConfigValue(domain=is_physical_parameter_block))
    CONFIG.declare("sink_property_package", ConfigValue(domain=is_physical_parameter_block))
    CONFIG.declare("refrigerant_property_package", ConfigValue(default=None, domain=is_physical_parameter_block))
    CONFIG.declare("fidelities", ConfigValue(default=None))

    def build(self):
        super().build()
        if self.config.dynamic or self.config.has_holdup:
            raise ValueError("Only steady-state operation without holdup is supported")
        time = self.flowsheet().time
        for side in ("source", "sink"):
            package = getattr(self.config, f"{side}_property_package")
            for direction in ("inlet", "outlet"):
                name = f"{side}_{direction}"
                state = states(package, time, inlet=direction == "inlet")
                self.add_component(f"{name}_state", state)
                self.add_port(name, state)
        units = self.config.sink_property_package.get_metadata().get_derived_units
        self.electrical_power = Var(time, initialize=1000, bounds=(0, None), units=units("power"))
        self.heating_duty = Expression(
            time, rule=lambda b, t: convert(
                enthalpy_flow(b.sink_outlet_state[t]) - enthalpy_flow(b.sink_inlet_state[t]),
                b.electrical_power[t],
            ),
        )
        self.cooling_duty = Expression(
            time, rule=lambda b, t: b.heating_duty[t] - b.electrical_power[t],
        )
        self.build_fidelities(
            self.config.fidelities if self.config.fidelities is not None
            else {"cop": COPHeatPump()}, self,
        )

    def initialize_build(self, *, solver=None, optarg=None):
        """Solve the selected representation with caller-provided specifications.

        Inlet states are temporarily fixed. Power and representation-specific
        parameters retain their fixation status, allowing rating or power prediction.
        """
        solver = get_solver(solver, optarg) if solver is None or isinstance(solver, str) else solver
        inputs = []
        for port in (self.source_inlet, self.sink_inlet):
            for variable in port.vars.values():
                inputs.extend(variable.values())
        with fixed_inputs(inputs):
            name = self.active_fidelity
            result = self._builders[name].initialize(
                self.fidelities[name], self, model=self, solver=solver,
            )
            if not check_optimal_termination(result):
                raise InitializationError(f"{self.name}: {name} initialization failed")
        return result
