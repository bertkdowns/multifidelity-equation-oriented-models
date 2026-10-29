"""Integration checks against the actual optional Ahuora property packages."""

import pytest
from idaes.core.util.model_statistics import degrees_of_freedom
from pyomo.environ import ConcreteModel, Constraint, Var, value
from pyomo.util.calc_var_value import calculate_variable_from_constraint
from pyomo.util.check_units import assert_units_consistent

from multifidelity.model_language.standard.humid_air import build_humid_air
from multifidelity.model_language.standard.thermo import build_helmholtz_ph


@pytest.mark.parametrize("fluid", ["h2o", "propane"])
def test_helmholtz_native_properties_and_saturation(fluid):
    pytest.importorskip("ahuora_property_packages")
    from idaes.models.properties.general_helmholtz import helmholtz_available

    if not helmholtz_available():
        pytest.skip("IDAES Helmholtz compiled functions are not installed")
    model = ConcreteModel()
    mapping = build_helmholtz_ph(model, {"fluid": fluid, "viscosity_phase": "Vap"})
    assert_units_consistent(model)
    assert degrees_of_freedom(model) == 2
    assert not any(variable.fixed for variable in model.component_data_objects(Var))
    state = model.states[0]
    state.pressure.set_value(101325)
    state.enth_mass.set_value(500000)
    for name in [
        "temperature",
        "density",
        "entropy",
        "temperature_bubble",
        "temperature_dew",
    ]:
        calculate_variable_from_constraint(
            mapping["properties." + name], getattr(model, name + "_equation")
        )
    assert value(model.temperature) == pytest.approx(value(state.temperature))
    assert value(model.density) == pytest.approx(value(state.dens_mass))
    assert value(model.entropy) == pytest.approx(value(state.entr_mass))
    assert value(model.temperature_bubble) == pytest.approx(
        value(state.temperature_sat)
    )
    assert value(model.temperature_dew) == pytest.approx(
        value(model.temperature_bubble)
    )
    mapping["state.pressure"].fix()
    mapping["state.enthalpy"].fix()
    assert degrees_of_freedom(model) == 0


def test_humid_air_matches_packaged_surrogate_with_si_coordinates():
    pytest.importorskip("ahuora_property_packages")
    from ahuora_property_packages.humid_air.HumidAirSurrogate import HAirParameterBlock

    model = ConcreteModel()
    mapping = build_humid_air(model, {})
    assert_units_consistent(model)
    assert degrees_of_freedom(model) == 3
    assert not any(variable.fixed for variable in model.component_data_objects(Var))
    state = model.states[0]
    assert state.component("surrogate") is None
    inputs = [300.0, 101325.0, 0.01, 0.99]
    reference = ConcreteModel()
    reference.parameters = HAirParameterBlock()
    reference.states = reference.parameters.build_state_block([0], defined_state=False)
    native = reference.states[0]
    for variable, number in zip(
        [
            native.temperature,
            native.pressure,
            native.mole_frac_comp["water"],
            native.mole_frac_comp["air"],
        ],
        inputs,
    ):
        variable.set_value(number)
    expected = []
    for variable, constraint in zip(
        [
            native.relative_humidity,
            native.temperature_wet_bulb,
            native.enth_mol,
            native.entr_mol,
            native.vol_mol,
        ],
        native.surrogate.component_data_objects(Constraint),
    ):
        calculate_variable_from_constraint(variable, constraint)
        expected.append(value(variable))
    for index, number in enumerate(inputs):
        getattr(model, f"coordinate_{index}").set_value(number)
    # Evaluate the rebuilt polynomial constraints, with no nonlinear solver.
    for index, constraint in enumerate(
        model.surrogate.component_data_objects(Constraint)
    ):
        coordinate = getattr(model, f"coordinate_{index + 4}")
        calculate_variable_from_constraint(coordinate, constraint)
        assert value(coordinate) == pytest.approx(expected[index])
    for path in ["state.temperature", "state.pressure", "state.water_mole_fraction"]:
        mapping[path].fix()
    assert degrees_of_freedom(model) == 0
