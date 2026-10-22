"""Navigate resolved definitions without requesting a Pyomo construction."""

import pytest

from multifidelity.model_language.resolution import Library, ResolvedModel
from multifidelity.model_language.definitions import ConcreteModelReference, Model


def test_generic_references_are_resolved_during_navigation():
    library = Library()
    root = library.resolve("water_property_pair")
    pair = root.relationships["evaluate"].models["states"]
    assert isinstance(pair, ResolvedModel)
    assert pair.id == "property_pair"
    assert pair.model_arguments["FluidProperties"].id == "water_state"
    states = pair.relationships["evaluate"].models
    assert states["inlet"].definition is library.get("water_state")
    assert states["outlet"].definition is states["inlet"].definition
    assert states["inlet"].path != states["outlet"].path
    assert states["inlet"].structs["state"].variables["pressure"].unit == "Pa"
    assert (
        states["inlet"]
        .relationships["constant_properties"]
        .constraints["density"]
        .determines
        == "properties.density"
    )


def test_recursive_definitions_are_not_eagerly_unrolled():
    library = Library()
    library.models["recursive"] = Model.model_validate(
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
    root = library.resolve("heat_pump")
    assert root.relationships["aggregate"].models == {}
    with pytest.raises(ValueError, match="Unknown model"):
        root.relationships["cycle"].models


def test_interface_errors_are_available_without_conversion():
    library = Library()
    library.get("water_state").structs["state"].direction = "output"
    with pytest.raises(ValueError, match="incompatible required struct"):
        library.resolve("water_property_pair").relationships["evaluate"].models


def test_unknown_generic_parameter_is_reported_without_conversion():
    library = Library()
    library.get("water_property_pair").relationships["evaluate"].models["states"] = (
        ConcreteModelReference.model_validate(
            {
                "model": "property_pair",
                "model_arguments": {"FluidProperties": {"model_parameter": "Missing"}},
            }
        )
    )
    with pytest.raises(ValueError, match="unknown model parameter"):
        library.resolve("water_property_pair").relationships["evaluate"].models


def test_fresh_views_see_definition_edits():
    library = Library()
    before = library.resolve("water_property_pair").relationships["evaluate"].models
    library.get("water_property_pair").relationships["evaluate"].models.clear()
    assert "states" in before
    assert library.resolve("water_property_pair").relationships["evaluate"].models == {}
