"""Symbolic providers compose through the same public interface as JSON models."""

from copy import deepcopy
import json

import pytest
from pydantic import ValidationError
from pyomo.environ import Var, value, units
from pyomo.util.check_units import assert_units_consistent

from examples.custom_models.build import HERE, build_pump, make_library
from multifidelity.model_language import Library, build_model, required_inputs
from multifidelity.model_language.definitions import Model, Relationship


def selection():
    return json.loads((HERE / "implementation.json").read_text())


def test_wrapper_composes_generic_property_model_and_external_pump():
    library = make_library()
    chosen = selection()
    model = build_model("pump_flowsheet", chosen, library=library)
    assert_units_consistent(model)
    assert set(required_inputs("pump_flowsheet", chosen, library=library)) == {
        "pump.inlet.flow",
        "pump.parameters.pressure_rise",
        "pump.parameters.efficiency",
    }
    assert all(
        not v.fixed and v.value is None for v in model.component_data_objects(Var)
    )

    pump = model.fs.root.relationship.models.pump
    core = pump.relationship.models.core
    native = core.relationship.provider
    native.pressure_rise.set_value(100)
    core.structs.parameters.pressure_rise.set_value(100_000)
    native.work.set_value(2)
    core.structs.performance.work.set_value(2000)
    # Binding order follows the public declaration order: pressure and power
    # must convert kPa -> Pa and kW -> W rather than equate raw numbers.
    assert value(core.relationship.bindings[3].body) == pytest.approx(0)
    assert value(core.relationship.bindings[5].body) == pytest.approx(0)


def test_inspection_requires_no_registered_provider_and_json_alternative_still_builds():
    library = Library(HERE / "models")
    chosen = selection()
    assert len(required_inputs("pump_flowsheet", chosen, library=library)) == 3
    assert library.resolve("liquid_density").structs["properties"].direction == "output"
    # The absent density provider is irrelevant when its JSON alternative is selected.
    chosen["submodels"]["pump"]["submodels"]["properties"]["relationship"] = (
        "constant_json"
    )
    library.register_provider("example.pump", build_pump)
    build_model("pump_flowsheet", chosen, library=library)


def test_repeated_occurrences_get_fresh_blocks_and_config():
    library = Library(HERE / "models")
    library.models["pair"] = Model.model_validate(
        {
            "id": "pair",
            "structs": {},
            "relationships": {
                "both": {
                    "models": {
                        "first": {"model": "liquid_density"},
                        "second": {"model": "liquid_density"},
                    }
                }
            },
        }
    )
    configs = []

    def density(block, config):
        configs.append(deepcopy(config))
        config["density_kg_m3"] = 1
        block.rho = Var(units=units.kg / units.m**3)
        return {"properties.density": block.rho}

    library.register_provider("example.liquid_density", density)
    model = build_model(
        "pair",
        {
            "model": "pair",
            "relationship": "both",
            "submodels": {
                "first": {"relationship": "constant_python"},
                "second": {"relationship": "constant_python"},
            },
        },
        library=library,
    )
    children = model.fs.root.relationship.models
    assert (
        children.first.relationship.provider.rho
        is not children.second.relationship.provider.rho
    )
    assert configs == [{"density_kg_m3": 997}, {"density_kg_m3": 997}]
    # No equation was supplied: authored dependency declarations are trusted.
    assert library.get("liquid_density").relationships[
        "constant_python"
    ].external.config == {"density_kg_m3": 997}


def test_declared_dependencies_support_parent_inverse_determination():
    library = make_library()
    library.models["inverse"] = Model.model_validate(
        {
            "id": "inverse",
            "structs": {},
            "relationships": {
                "evaluate": {
                    "models": {"core": {"model": "pump_core"}},
                    "constraints": {
                        "power": {
                            "lhs": "core.performance.work",
                            "rhs": "2000 * units.W",
                            "determines": "core.parameters.pressure_rise",
                        }
                    },
                }
            },
        }
    )
    chosen = {
        "model": "inverse",
        "relationship": "evaluate",
        "submodels": {"core": {"relationship": "python"}},
    }
    model = build_model("inverse", chosen, library=library)
    assert_units_consistent(model)
    assert "core.parameters.pressure_rise" not in required_inputs(
        "inverse", chosen, library=library
    )


@pytest.mark.parametrize("kind", ["missing", "extra", "expression", "units"])
def test_invalid_interface_mappings_include_occurrence_and_provider(kind):
    library = Library(HERE / "models")

    def invalid(block, config):
        block.x = Var(units=units.s if kind == "units" else units.kg / units.m**3)
        if kind == "missing":
            return {}
        if kind == "extra":
            return {"properties.density": block.x, "unknown": block.x}
        return {"properties.density": block.x + 1 if kind == "expression" else block.x}

    library.register_provider("example.liquid_density", invalid)
    with pytest.raises(
        ValueError,
        match="liquid_density.constant_python: provider 'example.liquid_density'",
    ):
        build_model(
            "liquid_density",
            {"model": "liquid_density", "relationship": "constant_python"},
            library=library,
        )


def test_missing_duplicate_and_failing_providers():
    library = Library(HERE / "models")
    chosen = {"model": "liquid_density", "relationship": "constant_python"}
    with pytest.raises(ValueError, match="Unknown provider: example.liquid_density"):
        build_model("liquid_density", chosen, library=library)

    def broken(block, config):
        raise RuntimeError("bad artifact")

    library.register_provider("example.liquid_density", broken)
    with pytest.raises(ValueError, match="Duplicate provider"):
        library.register_provider("example.liquid_density", broken)
    with pytest.raises(
        ValueError, match="liquid_density.constant_python.*bad artifact"
    ) as error:
        build_model("liquid_density", chosen, library=library)
    assert isinstance(error.value.__cause__, RuntimeError)


@pytest.mark.parametrize(
    "field, contents",
    [
        ("models", {"child": {"model": "liquid_density"}}),
        ("constraints", {"eq": {"lhs": "a.x", "rhs": "b.x", "determines": "a.x"}}),
        ("connections", {"link": {"from": "a", "to": "b"}}),
    ],
)
def test_external_and_json_composition_are_exclusive(field, contents):
    with pytest.raises(ValidationError, match="use a JSON wrapper"):
        Relationship.model_validate(
            {"external": {"provider": "example", "dependencies": {}}, field: contents}
        )


def test_external_definitions_round_trip_and_default_config():
    model = Model.model_validate_json((HERE / "models/pump_core.json").read_text())
    assert model.relationships["python"].external.config == {}
    assert Model.model_validate(model.model_dump(by_alias=True)) == model


@pytest.mark.parametrize(
    "dependencies",
    [{}, {"unknown.output": []}, {"properties.density": ["unknown.input"]}],
)
def test_dependency_declarations_use_public_paths(dependencies):
    library = Library(HERE / "models")
    library.get("liquid_density").relationships[
        "constant_python"
    ].external.dependencies = dependencies
    with pytest.raises(ValueError, match="dependencies"):
        required_inputs(
            "liquid_density",
            {"model": "liquid_density", "relationship": "constant_python"},
            library=library,
        )


def test_inspection_does_not_call_registered_providers():
    library = Library(HERE / "models")

    def forbidden(block, config):
        raise AssertionError("Inspection must not construct providers")

    library.register_provider("example.pump", forbidden)
    library.register_provider("example.liquid_density", forbidden)
    assert len(required_inputs("pump_flowsheet", selection(), library=library)) == 3
