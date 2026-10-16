"""An IDAES pure-liquid-water package with selectable property equations."""

from collections.abc import Mapping

from idaes.core import (
    Component,
    EnergyBalanceType,
    LiquidPhase,
    MaterialBalanceType,
    MaterialFlowBasis,
    PhysicalParameterBlock,
    StateBlock,
    StateBlockData,
    declare_process_block_class,
)
from idaes.core.solvers import get_solver
from idaes.core.util.exceptions import InitializationError
from idaes.core.util.initialization import fix_state_vars, revert_state_vars
from pyomo.common.config import ConfigValue
from pyomo.core.base.var import ScalarVar
from pyomo.environ import Expression, Param, Var, check_optimal_termination, units as u
from pyomo.opt import SolverResults
from pyomo.opt.base.solvers import OptSolver

from ..base import Fidelity, MultiFidelityMixin, fixed_inputs
from .helmholtz import HelmholtzWater
from .interface import SharedWater
from .linear import LinearWater


@declare_process_block_class("WaterParameterBlock")
class WaterParameterData(PhysicalParameterBlock):
    CONFIG = PhysicalParameterBlock.CONFIG()
    CONFIG.declare("fidelities", ConfigValue(default=None))

    def build(self) -> None:
        super().build()
        self._state_block_class = WaterStateBlock  # noqa: F821 (generated below by IDAES)
        self.Liq = LiquidPhase()
        self.H2O = Component()
        # Reference h, s and density match IAPWS-95 at 298.15 K, 101325 Pa.
        self.temperature_ref = Param(initialize=298.15, mutable=True, units=u.K)
        self.pressure_ref = Param(initialize=101325, mutable=True, units=u.Pa)
        self.cp_ref = Param(initialize=4180, mutable=True, units=u.J / u.kg / u.K)
        self.enthalpy_ref = Param(
            initialize=104920.1198085, mutable=True, units=u.J / u.kg
        )
        self.entropy_ref = Param(
            initialize=367.1996421, mutable=True, units=u.J / u.kg / u.K
        )
        self.density_ref = Param(
            initialize=997.04763676, mutable=True, units=u.kg / u.m**3
        )
        self.expansion_ref = Param(initialize=2.57e-4, mutable=True, units=1 / u.K)
        self.compressibility_ref = Param(
            initialize=4.6e-10, mutable=True, units=1 / u.Pa
        )
        self.builders: Mapping[str, Fidelity[SharedWater]] = (
            self.config.fidelities
            if self.config.fidelities is not None
            else {
                "linear": LinearWater(),
                "helmholtz": HelmholtzWater(),
            }
        )

    def get_helmholtz_parameters(self) -> PhysicalParameterBlock:
        """Construct shared IAPWS constants only if a Helmholtz builder needs them."""
        if not hasattr(self, "helmholtz_parameters"):
            from idaes.models.properties.iapws95 import Iapws95ParameterBlock
            from idaes.models.properties.general_helmholtz import AmountBasis, PhaseType

            self.helmholtz_parameters = Iapws95ParameterBlock(
                phase_presentation=PhaseType.L, amount_basis=AmountBasis.MASS
            )
        return self.helmholtz_parameters

    @classmethod
    def define_metadata(cls, metadata):
        metadata.add_default_units(
            {
                "time": u.s,
                "length": u.m,
                "mass": u.kg,
                "amount": u.mol,
                "temperature": u.K,
            }
        )
        metadata.add_properties(
            {
                name: {"method": None}
                for name in (
                    "flow_mass",
                    "temperature",
                    "pressure",
                    "enth_mass",
                    "entr_mass",
                    "dens_mass",
                    "cp_mass",
                    "enth_mass_phase",
                    "entr_mass_phase",
                    "dens_mass_phase",
                    "cp_mass_phase",
                    "energy_internal_mass_phase",
                )
            }
        )


class _WaterStateBlock(StateBlock):
    def initialize(
        self, state_args=None, hold_state=False, solver=None, optarg=None, outlvl=None
    ):
        flags = fix_state_vars(self, state_args)
        try:
            for state in self.values():
                state.initialize(solver=solver, optarg=optarg)
        except Exception:
            revert_state_vars(self, flags)
            raise
        if hold_state:
            return flags
        self.release_state(flags)

    def release_state(self, flags, outlvl=None):
        revert_state_vars(self, flags)


@declare_process_block_class("WaterStateBlock", block_class=_WaterStateBlock)
class WaterStateData(MultiFidelityMixin[SharedWater], StateBlockData):
    def build(self) -> None:
        super().build()
        self.flow_mass = Var(initialize=1, bounds=(0, None), units=u.kg / u.s)
        self.temperature = Var(initialize=298.15, bounds=(273.16, 373.15), units=u.K)
        self.pressure = Var(initialize=101325, bounds=(1e5, 5e6), units=u.Pa)
        self.enth_mass = Var(initialize=104920, units=u.J / u.kg)
        self.entr_mass = Var(initialize=367.2, units=u.J / u.kg / u.K)
        self.dens_mass = Var(initialize=997, bounds=(1, None), units=u.kg / u.m**3)
        self.cp_mass = Var(initialize=4180, bounds=(1, None), units=u.J / u.kg / u.K)
        self.enth_mass_phase = Expression(
            self.phase_list, rule=lambda b, p: b.enth_mass
        )
        self.entr_mass_phase = Expression(
            self.phase_list, rule=lambda b, p: b.entr_mass
        )
        self.dens_mass_phase = Expression(
            self.phase_list, rule=lambda b, p: b.dens_mass
        )
        self.cp_mass_phase = Expression(self.phase_list, rule=lambda b, p: b.cp_mass)
        self.energy_internal_mass_phase = Expression(
            self.phase_list, rule=lambda b, p: b.enth_mass - b.pressure / b.dens_mass
        )
        self._shared = SharedWater(
            self.params,
            self.flow_mass,
            self.temperature,
            self.pressure,
            self.enth_mass,
            self.entr_mass,
            self.dens_mass,
            self.cp_mass,
        )
        self.build_fidelities(self.params.builders, self._shared)

    def define_state_vars(self) -> dict[str, ScalarVar]:
        return {
            "flow_mass": self.flow_mass,
            "temperature": self.temperature,
            "pressure": self.pressure,
        }

    def get_material_flow_basis(self):
        return MaterialFlowBasis.mass

    def get_material_flow_terms(self, phase, component):
        return self.flow_mass

    def get_enthalpy_flow_terms(self, phase):
        return self.flow_mass * self.enth_mass

    def get_material_density_terms(self, phase, component):
        return self.dens_mass

    def get_energy_density_terms(self, phase):
        return self.dens_mass * self.energy_internal_mass_phase[phase]

    def default_material_balance_type(self):
        return MaterialBalanceType.componentTotal

    def default_energy_balance_type(self):
        return EnergyBalanceType.enthalpyTotal

    def initialize(
        self,
        *,
        solver: str | OptSolver | None = None,
        optarg: dict[str, str | int | float] | None = None,
    ) -> SolverResults:
        solver = (
            get_solver(solver, optarg)
            if solver is None or isinstance(solver, str)
            else solver
        )
        with fixed_inputs(self.define_state_vars().values()):
            name = self.active_fidelity
            result = self._builders[name].initialize(
                self.fidelities[name], self._shared, model=self, solver=solver
            )
            if not check_optimal_termination(result):
                raise InitializationError(f"{self.name}: {name} initialization failed")
        return result
