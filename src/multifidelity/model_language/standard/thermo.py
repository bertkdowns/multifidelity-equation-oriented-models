"""Mass-basis Ahuora Helmholtz state providers."""

from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import JsonValue

if TYPE_CHECKING:
    from pyomo.core.base.block import BlockData
    from pyomo.core.base.var import VarData


@contextmanager
def _fluid_data(fluid):
    """Embed Ahuora's additional n-butane data without retaining its global path.

    IDAES embeds the data directory in each constructed external expression.
    Construct all reported properties inside this context, before restoring the
    previous directory and its component registry. No files are copied/modified.
    """
    if fluid != 'n-butane':
        yield
        return
    from ahuora_property_packages.helmholtz import parameters
    from idaes.models.properties.general_helmholtz.components.parameters import (
        get_parameter_path, set_parameter_path,
    )
    previous = get_parameter_path()
    try:
        set_parameter_path(str(Path(parameters.__file__).parent))
        yield
    finally:
        set_parameter_path(previous)


def _build_state(block, config, state_vars):
    from idaes.models.properties.general_helmholtz import AmountBasis
    from ahuora_property_packages.helmholtz.helmholtz_extended import HelmholtzExtendedParameterBlock
    from pyomo.environ import Constraint, units as u

    block.parameters = HelmholtzExtendedParameterBlock(
        pure_component=config.get('fluid', 'h2o'), state_vars=state_vars,
        amount_basis=AmountBasis.MASS,
    )
    block.states = block.parameters.build_state_block(
        [0], defined_state=True, has_phase_equilibrium=False,
    )
    state = block.states[0]
    block.flow_closure = Constraint(expr=state.flow_mass == 1 * u.kg / u.s)
    return state


def _output(block, mapping, name, expression, unit):
    from pyomo.environ import Constraint, Var

    variable = Var(initialize=1, units=unit)
    block.add_component(name, variable)
    block.add_component(name + '_equation', Constraint(expr=variable == expression))
    mapping['properties.' + name] = variable


def scale_helmholtz_ph(block, config):
    """Nominal mass-basis scales for native PH state and property variables."""
    from idaes.core.util.scaling import set_scaling_factor
    state = block.states[0]
    set_scaling_factor(state.pressure, 1e-5)
    set_scaling_factor(state.enth_mass, 1e-5)
    set_scaling_factor(state.flow_mass, 1)
    factors = {
        'temperature': 1/300, 'density': 1e-3, 'heat_capacity': 1e-3,
        'entropy': 1e-3, 'vapor_fraction': 1, 'temperature_bubble': 1/300,
        'temperature_dew': 1/300, 'viscosity': 1e3,
        'enthalpy_liquid_sat': 1e-5, 'enthalpy_vapor_sat': 1e-5,
        'enthalpy_liquid': 1e-5, 'enthalpy_vapor': 1e-5,
    }
    for name, factor in factors.items():
        if hasattr(block, name):
            set_scaling_factor(getattr(block, name), factor)


def build_helmholtz_ph(block: 'BlockData', config: dict[str, JsonValue]) -> dict[str, 'VarData']:
    """PH state; optional viscosity is omitted for n-butane's EOS-only data."""
    from idaes.models.properties.general_helmholtz import StateVars
    from pyomo.environ import units as u

    with _fluid_data(config.get('fluid', 'h2o')):
        state = _build_state(block, config, StateVars.PH)
        expressions = {
            'temperature': (state.temperature, u.K),
            'density': (state.dens_mass, u.kg / u.m**3),
            'heat_capacity': (state.cp_mass, u.J / u.kg / u.K),
            'entropy': (state.entr_mass, u.J / u.kg / u.K),
            'vapor_fraction': (state.vapor_frac, u.dimensionless),
            'temperature_bubble': (state.temperature_sat, u.K),
            'temperature_dew': (state.temperature_sat, u.K),
            'enthalpy_liquid_sat': (state.enth_mass_sat_phase['Liq'], u.J / u.kg),
            'enthalpy_vapor_sat': (state.enth_mass_sat_phase['Vap'], u.J / u.kg),
            'enthalpy_liquid': (state.enth_mass_phase['Liq'], u.J / u.kg),
            'enthalpy_vapor': (state.enth_mass_phase['Vap'], u.J / u.kg),
        }
        if config.get('include_viscosity', True):
            expressions['viscosity'] = (
                state.visc_d_phase[config.get('viscosity_phase', 'Liq')], u.Pa * u.s,
            )
        mapping = {'state.pressure': state.pressure, 'state.enthalpy': state.enth_mass}
        for name, (expression, unit) in expressions.items():
            _output(block, mapping, name, expression, unit)
        return mapping
