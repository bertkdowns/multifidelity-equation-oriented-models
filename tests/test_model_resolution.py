"""Navigate resolved definitions without requesting a Pyomo construction."""

import pytest

from multifidelity.model_language.resolution import Library, ModelView
from multifidelity.model_language.definitions import ConcreteModelReference, ModelDocument


def test_generic_references_are_resolved_during_navigation():
    library = Library()
    root = library.resolve("water_state_block")
    pair = root.relationships["evaluate"].models["states"]
    assert isinstance(pair, ModelView)
    assert pair.id == "state_block"
    assert pair.model_arguments["FluidProperties"].id == "water_property_package"
    states = pair.relationships["evaluate"].models
    assert states["fluid"].definition is library.get("water_property_package")
    assert set(states) == {"fluid"}
    assert states["fluid"].path == "water_state_block.states.fluid"
    assert states["fluid"].structs["state"].variables["pressure"].unit == "Pa"
    assert (
        states["fluid"]
        .relationships["constant_properties"]
        .constraints["density"]
        .determines
        == "water.parameters.density"
    )


def test_recursive_definitions_are_not_eagerly_unrolled():
    library = Library()
    library.models["recursive"] = ModelDocument.model_validate(
        {
            "id": "recursive",
            "structs": {},
            "relationships": {"again": {"models": {"next": {"model": "recursive"}}}},
        }
    )
    root = library.resolve("recursive")
    child = root.relationships["again"].models["next"]
    assert child.definition is root.definition
    assert child.path == "recursive.next"


def test_unused_alternatives_need_not_resolve():
    library = Library()
    library.get("heat_pump").relationships["cycle"].models[
        "compressor"
    ].model = "absent"
    root = library.resolve("heat_pump_flowsheet").relationships["flowsheet"].models["heat_pump"]
    assert set(root.relationships["aggregate"].models) == {
        "cop_model", "source_inlet_state", "source_outlet_state",
        "sink_inlet_state", "sink_outlet_state", "power_model",
    }
    assert root.relationships["aggregate"].models["cop_model"].id == "prescribed_cop"
    with pytest.raises(ValueError, match="Unknown model"):
        root.relationships["cycle"].models


def test_interface_errors_are_available_without_conversion():
    library = Library()
    library.get("water_property_package").structs["state"].direction = "output"
    with pytest.raises(ValueError, match="incompatible required struct"):
        library.resolve("water_state_block").relationships["evaluate"].models


def test_unknown_generic_parameter_is_reported_without_conversion():
    library = Library()
    library.get("water_state_block").relationships["evaluate"].models["states"] = (
        ConcreteModelReference.model_validate(
            {
                "model": "state_block",
                "model_arguments": {"FluidProperties": {"model_parameter": "Missing"}},
            }
        )
    )
    with pytest.raises(ValueError, match="unknown model parameter"):
        library.resolve("water_state_block").relationships["evaluate"].models


def test_fresh_views_see_definition_edits():
    library = Library()
    before = library.resolve("water_state_block").relationships["evaluate"].models
    library.get("water_state_block").relationships["evaluate"].models.clear()
    assert "states" in before
    assert library.resolve("water_state_block").relationships["evaluate"].models == {}
