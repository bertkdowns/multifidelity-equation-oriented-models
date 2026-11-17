"""The standard definitions compose through existing generic interfaces."""

import json
from pathlib import Path

import pytest
from idaes.core.util.model_statistics import degrees_of_freedom
from pyomo.core.expr.visitor import identify_variables
from pyomo.environ import Constraint, Var, value
from pyomo.util.calc_var_value import calculate_variable_from_constraint
from pyomo.util.check_units import assert_units_consistent

from multifidelity.model_language import (
    BlockRegistry,
    build_model,
    register_standard_providers,
    required_inputs,
)


EXAMPLES = Path(__file__).parents[1] / "examples/model_language"


def choose(name):
    return json.loads((EXAMPLES / f"{name}.json").read_text())


def require_helmholtz():
    pytest.importorskip("ahuora_property_packages")
    from idaes.models.properties.general_helmholtz import helmholtz_available

    if not helmholtz_available():
        pytest.skip("IDAES Helmholtz compiled functions are not installed")


def test_registration_and_inspection_do_not_construct_optional_providers(monkeypatch):
    import multifidelity.model_language.standard as standard

    def forbidden(*args, **kwargs):
        raise AssertionError("Registration/inspection must not construct blocks")

    for name in ("build_compressor_map", "build_helmholtz_ph", "build_humid_air"):
        monkeypatch.setattr(standard, name, forbidden)
    registry = BlockRegistry()
    register_standard_providers(registry)
    assert registry.get_provider("standard.humid_air") is forbidden
    assert set(
        required_inputs(
            "mapped_propane_compressor",
            choose("mapped_propane_compressor"),
            registry=registry,
        )
    ) == {
        "compressor.inlet.pressure",
        "compressor.inlet.enthalpy",
        "compressor.parameters.pressure_rise",
        "compressor.parameters.motor_efficiency",
    }
    assert set(
        required_inputs("humid_air_state", choose("humid_air_state"), registry=registry)
    ) == {"state.temperature", "state.pressure", "state.water_mole_fraction"}


def test_richer_helmholtz_interface_satisfies_existing_state_block():
    require_helmholtz()
    registry = BlockRegistry()
    register_standard_providers(registry)
    selection = choose("helmholtz_water_state_block")
    model = build_model("helmholtz_water_state_block", selection, registry=registry)
    assert_units_consistent(model)
    assert degrees_of_freedom(model) == 2
    # Flow is a required stream input but thermodynamic equations do not use it.
    assert (
        len(
            required_inputs("helmholtz_water_state_block", selection, registry=registry)
        )
        == 3
    )
    # Saturation is part of the common thermodynamic projection; transport is not.
    pair = model.fs.root.formulation.blocks.states
    assert hasattr(pair.structs.properties, "temperature_dew")
    assert not hasattr(pair.structs.properties, "viscosity")
    assert (
        "temperature_dew"
        in registry.get("helmholtz_water_ph").structs["properties"].variables
    )


def test_mapped_compressor_rejects_property_model_without_saturation():
    registry = BlockRegistry()
    reference = (
        registry.get("mapped_propane_compressor")
        .formulations["evaluate"]
        .blocks["compressor"]
    )
    reference.block_arguments["FluidProperties"].block = "water_property_package"
    del registry.get("water_property_package").structs["properties"].variables["temperature_bubble"]
    with pytest.raises(
        ValueError, match="missing required variable properties.temperature_bubble"
    ):
        required_inputs(
            "mapped_propane_compressor",
            choose("mapped_propane_compressor"),
            registry=registry,
        )


def test_affine_water_exposes_liquid_fraction_and_saturation_temperatures():
    registry = BlockRegistry()
    assert (
        "temperature_dew"
        in registry.get("water_property_package").structs["properties"].variables
    )
    assert (
        len(
            required_inputs(
                "water_state_block",
                EXAMPLES / "water_state_block_evaluate.json",
                registry=registry,
            )
        )
        == 3
    )


def test_cli_build_registers_standard_providers(monkeypatch, capsys):
    import sys
    from multifidelity.model_language.__main__ import main

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "model_language",
            "en12900_compressor_map",
            str(EXAMPLES / "en12900_compressor_map.json"),
            "--standard-providers",
        ],
    )
    main()
    assert "electrical_power" in capsys.readouterr().out


def test_cli_input_inspection_does_not_need_providers(monkeypatch, capsys):
    import sys
    import multifidelity.model_language.__main__ as cli

    def forbidden(*args):
        raise AssertionError(
            "Input inspection must not register or construct feeds"
        )

    monkeypatch.setattr(cli, "register_standard_providers", forbidden)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "model_language",
            "mapped_propane_compressor",
            str(EXAMPLES / "mapped_propane_compressor.json"),
            "--standard-providers",
            "--required-inputs",
        ],
    )
    cli.main()
    assert len(capsys.readouterr().out.splitlines()) == 4


@pytest.mark.parametrize(
    "name,inputs",
    [
        ("helmholtz_water_ph", 2),
        ("helmholtz_propane_ph", 2),
        ("humid_air_state", 3),
        ("en12900_compressor_map", 2),
        ("mapped_propane_compressor", 4),
    ],
)
def test_standard_catalogs_build_with_only_declared_operating_inputs(name, inputs):
    if "helmholtz" in name or name == "mapped_propane_compressor":
        require_helmholtz()
    if name == "humid_air_state":
        pytest.importorskip("ahuora_property_packages")
    registry = BlockRegistry()
    register_standard_providers(registry)
    model = build_model(name, choose(name), registry=registry)
    assert_units_consistent(model)
    assert degrees_of_freedom(model) == inputs
    assert len(required_inputs(name, choose(name), registry=registry)) == inputs
    public = [v for v in model.component_data_objects(Var) if ".structs." in v.name]
    assert all(not v.fixed for v in public)


def _evaluate_explicit_equations(model):
    """Evaluate the acyclic example without relying on a nonlinear solver."""
    pending = list(model.component_data_objects(Constraint, active=True))
    while pending:
        remaining = []
        progressed = False
        for equation in pending:
            unknowns = [v for v in identify_variables(equation.body) if v.value is None]
            if len(unknowns) == 1:
                calculate_variable_from_constraint(unknowns[0], equation)
                progressed = True
            elif unknowns:
                remaining.append(equation)
        if not progressed:
            assert not remaining, [eq.name for eq in remaining]
        pending = remaining


def test_composed_compressor_matches_source_rating_and_energy_balance():
    require_helmholtz()
    from idaes.models.properties.general_helmholtz import (
        HelmholtzThermoExpressions,
        AmountBasis,
    )

    registry = BlockRegistry()
    register_standard_providers(registry)
    model = build_model(
        "mapped_propane_compressor",
        choose("mapped_propane_compressor"),
        registry=registry,
    )
    compressor = model.fs.root.formulation.blocks.compressor
    inlet_provider = compressor.formulation.blocks.inlet_state.formulation.blocks.fluid.formulation.slices[0].provider
    thermo = HelmholtzThermoExpressions(
        inlet_provider, inlet_provider.parameters, amount_basis=AmountBasis.MASS
    )
    # Same dew-temperature map coordinates as the source's default rating.
    pin = value(thermo.p_sat(T=280.35))
    pout = value(thermo.p_sat(T=327.55))
    hin = value(thermo.h_vap(T=291.45, p=pin))
    # Remove native initial guesses so each equality can fill one unknown.
    for variable in model.component_data_objects(Var):
        variable.set_value(None)
    compressor.structs.inlet.pressure[0].set_value(pin)
    compressor.structs.inlet.enthalpy[0].set_value(hin)
    compressor.structs.parameters.pressure_rise[0].set_value(pout - pin)
    compressor.structs.parameters.motor_efficiency[0].set_value(0.9)
    _evaluate_explicit_equations(model)
    performance = compressor.structs.performance
    assert value(performance.mass_flow[0]) == pytest.approx(40.28950867832506 / 3600)
    assert value(performance.electrical_power[0]) == pytest.approx(883.8508203054206)
    assert value(performance.rated_capacity[0]) == pytest.approx(3110.311326881739)
    assert value(performance.shaft_power[0]) == pytest.approx(
        0.9 * value(performance.electrical_power[0])
    )
    assert value(compressor.structs.outlet.enthalpy[0]) == pytest.approx(
        hin + value(performance.shaft_power[0]) / value(performance.mass_flow[0])
    )
    for equation in model.component_data_objects(Constraint, active=True):
        assert value(equation.body - equation.lower) == pytest.approx(0, abs=1e-6), (
            equation.name
        )
