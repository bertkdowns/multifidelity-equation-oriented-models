"""IDAES flowsheet integration for a shared-state heat exchanger."""

from collections.abc import Mapping

from idaes.core import UnitModelBlockData, declare_process_block_class
from idaes.core.solvers import get_solver
from idaes.core.util.config import is_physical_parameter_block
from idaes.core.util.exceptions import InitializationError
from pyomo.common.config import ConfigValue
from pyomo.environ import Expression, Var, check_optimal_termination, value
from pyomo.opt import SolverResults
from pyomo.opt.base.solvers import OptSolver

from ...base import Fidelity, MultiFidelityMixin, fixed_inputs
from ..streams import convert, enthalpy_flow, interpolate, states
from .distributed import DistributedHX
from .lumped import LumpedHX


@declare_process_block_class("HeatExchanger")
class HeatExchangerData(MultiFidelityMixin["HeatExchangerData"], UnitModelBlockData):
    CONFIG = UnitModelBlockData.CONFIG()
    CONFIG.declare(
        "hot_side_property_package", ConfigValue(domain=is_physical_parameter_block)
    )
    CONFIG.declare(
        "cold_side_property_package", ConfigValue(domain=is_physical_parameter_block)
    )
    CONFIG.declare("fidelities", ConfigValue(default=None))

    def build(self) -> None:
        super().build()
        if self.config.dynamic or self.config.has_holdup:
            raise ValueError("Only steady-state operation without holdup is supported")
        time = self.flowsheet().time
        hot = self.config.hot_side_property_package
        cold = self.config.cold_side_property_package
        for name, package, inlet in (
            ("hot_inlet", hot, True),
            ("hot_outlet", hot, False),
            ("cold_inlet", cold, True),
            ("cold_outlet", cold, False),
        ):
            state = states(package, time, inlet=inlet)
            self.add_component(f"{name}_state", state)
            self.add_port(name, state)
        units = hot.get_metadata().get_derived_units
        self.area = Var(initialize=10, bounds=(1e-8, None), units=units("area"))
        self.U = Var(
            time,
            initialize=100,
            bounds=(1e-8, None),
            units=units("heat_transfer_coefficient"),
        )
        self.length = Var(initialize=5, bounds=(1e-8, None), units=units("length"))
        self.hot_pressure_drop = Var(time, initialize=0, units=units("pressure"))
        self.cold_pressure_drop = Var(time, initialize=0, units=units("pressure"))
        self.hot_pressure_drop.fix(0)
        self.cold_pressure_drop.fix(0)
        self.heat_duty = Expression(
            time,
            rule=lambda b, t: convert(
                enthalpy_flow(b.cold_outlet_state[t])
                - enthalpy_flow(b.cold_inlet_state[t]),
                1 * units("power"),
            ),
        )
        builders: Mapping[str, Fidelity[HeatExchangerData]] = (
            self.config.fidelities
            if self.config.fidelities is not None
            else {
                "lumped": LumpedHX(),
                "distributed": DistributedHX(),
            }
        )
        self.build_fidelities(builders, self)

    def initialize_build(
        self,
        *,
        solver: str | OptSolver | None = None,
        optarg: dict[str, str | int | float] | None = None,
    ) -> SolverResults:
        """Initialize the selected formulation at the current inlet/design values."""
        solver = (
            get_solver(solver, optarg)
            if solver is None or isinstance(solver, str)
            else solver
        )
        inputs = [
            self.area,
            self.length,
            *self.U.values(),
            *self.hot_pressure_drop.values(),
            *self.cold_pressure_drop.values(),
        ]
        for port in (self.hot_inlet, self.cold_inlet):
            for variable in port.vars.values():
                inputs.extend(variable.values())
        with fixed_inputs(inputs):
            for t in self.flowsheet().time:
                for inlet, outlet, other in (
                    (
                        self.hot_inlet_state[t],
                        self.hot_outlet_state[t],
                        self.cold_inlet_state[t],
                    ),
                    (
                        self.cold_inlet_state[t],
                        self.cold_outlet_state[t],
                        self.hot_inlet_state[t],
                    ),
                ):
                    a = value(inlet.temperature)
                    b = value(convert(other.temperature, inlet.temperature))
                    if not min(a, b) < value(outlet.temperature) < max(a, b):
                        interpolate(outlet, inlet, inlet, 0)
                        independent = outlet.define_state_vars()
                        guess = 0.8 * a + 0.2 * b
                        if "temperature" in independent:
                            if not independent["temperature"].fixed:
                                independent["temperature"].set_value(guess)
                        elif "enth_mass" in independent:
                            if not independent["enth_mass"].fixed:
                                independent["enth_mass"].set_value(
                                    outlet.params.htpx(
                                        T=guess
                                        * outlet.params.get_metadata().get_derived_units(
                                            "temperature"
                                        ),
                                        p=outlet.pressure,
                                    )
                                )
            name = self.active_fidelity
            result = self._builders[name].initialize(
                self.fidelities[name], self, model=self, solver=solver
            )
            if not check_optimal_termination(result):
                raise InitializationError(f"{self.name}: {name} initialization failed")
        return result
