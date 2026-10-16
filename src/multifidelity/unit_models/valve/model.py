"""A liquid valve with shared states and selectable hydraulic closures."""

from collections.abc import Mapping

from idaes.core import UnitModelBlockData, declare_process_block_class
from idaes.core.solvers import get_solver
from idaes.core.util.config import is_physical_parameter_block
from idaes.core.util.exceptions import InitializationError
from pyomo.common.config import ConfigValue
from pyomo.environ import (
    Block,
    Expression,
    Param,
    Var,
    check_optimal_termination,
    sqrt,
    units as u,
)

from ...base import Fidelity, MultiFidelityMixin, fixed_inputs
from ..streams import add_stream_ports, stream_balance
from .interface import SharedValve
from .linear import LinearValve
from .pressure_flow import PressureFlowValve


@declare_process_block_class("Valve")
class ValveData(MultiFidelityMixin[SharedValve], UnitModelBlockData):
    CONFIG = UnitModelBlockData.CONFIG()
    CONFIG.declare("property_package", ConfigValue(domain=is_physical_parameter_block))
    CONFIG.declare("fidelities", ConfigValue(default=None))

    def build(self) -> None:
        super().build()
        if self.config.dynamic or self.config.has_holdup:
            raise ValueError("Only steady-state operation without holdup is supported")
        add_stream_ports(self, self.config.property_package)
        time = self.flowsheet().time
        cv_units = u.m**3 / u.s / u.Pa**0.5
        self.Cv = Var(initialize=1 / 3600, bounds=(1e-12, None), units=cv_units)
        self.opening = Var(time, initialize=0.5, bounds=(0, 1))
        self.alpha = Param(initialize=100, mutable=True)
        self.reference_density = Param(initialize=999, units=u.kg / u.m**3)
        self.nominal_Cv = Param(initialize=1 / 3600, mutable=True, units=cv_units)
        self.nominal_pressure_drop = Param(initialize=1e5, mutable=True, units=u.Pa)
        self.nominal_density = Param(initialize=1000, mutable=True, units=u.kg / u.m**3)
        self.nominal_opening = Param(initialize=0.5, mutable=True)
        self.nominal_flow = Expression(
            expr=self.nominal_Cv
            * self.alpha ** (self.nominal_opening - 1)
            * sqrt(
                self.nominal_pressure_drop
                * self.nominal_density
                * self.reference_density
            )
        )
        self.pressure_drop = Expression(
            time,
            rule=lambda b, t: b.inlet_state[t].pressure - b.outlet_state[t].pressure,
        )
        self.characteristic = Expression(
            time, rule=lambda b, t: b.alpha ** (b.opening[t] - 1)
        )
        # The normalization changes neither the law nor its roots, and gives an
        # interpretable dimensionless detailed-model residual at a simple solution.
        self.nonlinear_residual = Expression(
            time,
            rule=lambda b, t: (
                (
                    (b.inlet_state[t].flow_mass / b.inlet_state[t].dens_mass) ** 2
                    * (b.inlet_state[t].dens_mass / b.reference_density)
                    - b.Cv**2 * b.pressure_drop[t] * b.characteristic[t] ** 2
                )
                / (
                    (b.nominal_flow / b.nominal_density) ** 2
                    * (b.nominal_density / b.reference_density)
                )
            ),
        )
        self.balances = Block(time)
        for t in time:
            stream_balance(
                self.balances[t],
                self.inlet_state[t],
                self.outlet_state[t],
                0 * u.W,
                preserve_pressure=False,
            )
        shared = SharedValve(
            time,
            self.inlet_state,
            self.outlet_state,
            self.Cv,
            self.opening,
            self.alpha,
            self.pressure_drop,
            self.nonlinear_residual,
            self.nominal_flow,
            self.nominal_Cv,
            self.nominal_pressure_drop,
            self.nominal_density,
            self.nominal_opening,
        )
        self._shared = shared
        builders: Mapping[str, Fidelity[SharedValve]] = (
            self.config.fidelities
            if self.config.fidelities is not None
            else {
                "linear": LinearValve(),
                "pressure_flow": PressureFlowValve(),
            }
        )
        self.build_fidelities(builders, shared)

    def initialize_build(self, *, solver=None, optarg=None):
        solver = (
            get_solver(solver, optarg)
            if solver is None or isinstance(solver, str)
            else solver
        )
        inputs = [self.Cv, *self.opening.values()]
        for variable in self.inlet.vars.values():
            inputs.extend(variable.values())
        with fixed_inputs(inputs):
            name = self.active_fidelity
            result = self._builders[name].initialize(
                self.fidelities[name], self._shared, model=self, solver=solver
            )
            if not check_optimal_termination(result):
                raise InitializationError(f"{self.name}: {name} initialization failed")
        return result
