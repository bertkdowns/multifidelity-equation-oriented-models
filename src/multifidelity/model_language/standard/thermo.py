"""Ahuora Helmholtz pressure/enthalpy property provider."""

from typing import TYPE_CHECKING

from pydantic import JsonValue

if TYPE_CHECKING:
    from pyomo.core.base.block import BlockData
    from pyomo.core.base.var import VarData


def build_helmholtz_ph(
    block: "BlockData", config: dict[str, JsonValue]
) -> dict[str, "VarData"]:
    """Build pure-fluid properties without initializing or solving.

    ``viscosity_phase`` selects the reported phase viscosity (default ``Liq``).
    No two-phase effective-viscosity mixing rule is implied. Saturation outputs
    coincide for a pure fluid and are intended for subcritical pressures.
    """
    from idaes.models.properties.general_helmholtz import (
        AmountBasis,
        StateVars,
    )
    from ahuora_property_packages.helmholtz.helmholtz_extended import (
        HelmholtzExtendedParameterBlock,
    )
    from pyomo.environ import Constraint, Var, units as u

    block.parameters = HelmholtzExtendedParameterBlock(
        pure_component=config.get("fluid", "h2o"),
        state_vars=StateVars.PH,
        amount_basis=AmountBasis.MASS,
    )
    block.states = block.parameters.build_state_block(
        [0], defined_state=True, has_phase_equilibrium=False
    )
    state = block.states[0]
    block.flow_closure = Constraint(expr=state.flow_mass == 1 * u.kg / u.s)
    expressions = {
        "temperature": (state.temperature, u.K),
        "density": (state.dens_mass, u.kg / u.m**3),
        "heat_capacity": (state.cp_mass, u.J / u.kg / u.K),
        "viscosity": (
            state.visc_d_phase[config.get("viscosity_phase", "Liq")],
            u.Pa * u.s,
        ),
        "entropy": (state.entr_mass, u.J / u.kg / u.K),
        "vapor_fraction": (state.vapor_frac, u.dimensionless),
        "temperature_bubble": (state.temperature_sat, u.K),
        "temperature_dew": (state.temperature_sat, u.K),
    }
    mapping = {"state.pressure": state.pressure, "state.enthalpy": state.enth_mass}
    for name, (expression, unit) in expressions.items():
        variable = Var(initialize=1, units=unit)
        block.add_component(name, variable)
        block.add_component(name + "_equation", Constraint(expr=variable == expression))
        mapping["properties." + name] = variable
    return mapping
