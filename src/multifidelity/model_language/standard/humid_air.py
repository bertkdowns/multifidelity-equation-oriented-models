"""Ahuora humid-air PySMO state adapter."""

from typing import TYPE_CHECKING

from pydantic import JsonValue

if TYPE_CHECKING:
    from pyomo.core.base.block import BlockData
    from pyomo.core.base.var import VarData


def build_humid_air(
    block: "BlockData", config: dict[str, JsonValue]
) -> dict[str, "VarData"]:
    """Wrap the packaged surrogate with explicit SI training coordinates.

    PySMO polynomials use numerical SI coordinates, not dimensional expressions.
    Rebuild the existing loaded surrogate on dimensionless variables, then attach
    each coordinate to its native state variable with the corresponding SI unit.
    """
    from ahuora_property_packages.humid_air.HumidAirSurrogate import HAirParameterBlock
    from idaes.core.surrogate.surrogate_block import SurrogateBlock
    from pyomo.environ import Constraint, Var, units as u

    block.parameters = HAirParameterBlock()
    block.states = block.parameters.build_state_block([0], defined_state=False)
    state = block.states[0]
    block.flow_closure = Constraint(expr=state.flow_mol == 1 * u.mol / u.s)
    inputs = [
        (state.temperature, u.K),
        (state.pressure, u.Pa),
        (state.mole_frac_comp["water"], u.dimensionless),
        (state.mole_frac_comp["air"], u.dimensionless),
    ]
    outputs = [
        (state.relative_humidity, u.dimensionless),
        (state.temperature_wet_bulb, u.K),
        (state.enth_mol, u.J / u.mol),
        (state.entr_mol, u.J / u.mol / u.K),
        (state.vol_mol, u.m**3 / u.mol),
    ]
    surrogate = state.pysmo_surrogate
    state.del_component(state.surrogate)
    coordinates = []
    for index, (variable, unit) in enumerate(inputs + outputs):
        coordinate = Var(initialize=1, units=u.dimensionless)
        block.add_component(f"coordinate_{index}", coordinate)
        block.add_component(
            f"coordinate_link_{index}", Constraint(expr=variable == coordinate * unit)
        )
        coordinates.append(coordinate)
    block.surrogate = SurrogateBlock()
    block.surrogate.build_model(
        surrogate, input_vars=coordinates[:4], output_vars=coordinates[4:]
    )
    return {
        "state.temperature": state.temperature,
        "state.pressure": state.pressure,
        "state.water_mole_fraction": state.mole_frac_comp["water"],
        "properties.relative_humidity": state.relative_humidity,
        "properties.temperature_wet_bulb": state.temperature_wet_bulb,
        "properties.enthalpy": state.enth_mol,
        "properties.entropy": state.entr_mol,
        "properties.molar_volume": state.vol_mol,
    }
