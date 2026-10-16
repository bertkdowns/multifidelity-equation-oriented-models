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
from .distributed import DistributedHX
from .lumped import LumpedHX
from .interface import SharedHX
from ..streams import convert, enthalpy_flow, interpolate, states


@declare_process_block_class("HeatExchanger")
class HeatExchangerData(MultiFidelityMixin[SharedHX], UnitModelBlockData):
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
        self.heat_duty = Expression(
            time,
            rule=lambda b, t: convert(
                enthalpy_flow(b.cold_outlet_state[t])
                - enthalpy_flow(b.cold_inlet_state[t]),
                1 * units("power"),
            ),
        )
        self._shared = SharedHX(
            time,
            self.hot_inlet_state,
            self.hot_outlet_state,
            self.cold_inlet_state,
            self.cold_outlet_state,
            self.area,
            self.U,
            self.length,
            self.heat_duty,
        )
        builders: Mapping[str, Fidelity[SharedHX]] = (
            self.config.fidelities
            if self.config.fidelities is not None
            else {
                "lumped": LumpedHX(),
                "distributed": DistributedHX(),
            }
        )
        self.build_fidelities(builders, self._shared)

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
        inputs = [self.area, self.length, *self.U.values()]
        for port in (self.hot_inlet, self.cold_inlet):
            for variable in port.vars.values():
                inputs.extend(variable.values())
        with fixed_inputs(inputs):
            for t in self._shared.time:
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
                        if not outlet.temperature.fixed:
                            outlet.temperature.set_value(0.8 * a + 0.2 * b)
            name = self.active_fidelity
            result = self._builders[name].initialize(
                self.fidelities[name], self._shared, model=self, solver=solver
            )
            if not check_optimal_termination(result):
                raise InitializationError(f"{self.name}: {name} initialization failed")
        return result
