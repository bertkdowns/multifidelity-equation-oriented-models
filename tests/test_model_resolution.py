"""Navigate resolved definitions without requesting a Pyomo construction."""

import pytest

from multifidelity.model_language.resolution import BlockRegistry, BlockView
from multifidelity.model_language.definitions import ConcreteBlockReference, BlockDefinition


def test_generic_references_are_resolved_during_navigation():
    registry = BlockRegistry()
    root = registry.resolve("water_state_block")
    pair = root.formulations["evaluate"].blocks["states"]
    assert isinstance(pair, BlockView)
    assert pair.id == "state_block"
    assert pair.block_arguments["FluidProperties"].id == "water_property_package"
    states = pair.formulations["evaluate"].blocks
    assert states["fluid"].definition is registry.get("water_property_package")
    assert set(states) == {"fluid"}
    assert states["fluid"].path == "water_state_block.states.fluid"
    assert states["fluid"].structs["state"].variables["pressure"].unit == "Pa"
    assert (
        states["fluid"]
        .formulations["constant_properties"]
        .constraints["density"]
        .determines
        == "water.parameters.density"
    )


def test_recursive_definitions_are_not_eagerly_unrolled():
    registry = BlockRegistry()
    registry.blocks["recursive"] = BlockDefinition.model_validate(
        {
            "id": "recursive",
            "structs": {},
            "formulations": {"again": {"blocks": {"next": {"block": "recursive"}}}},
        }
    )
    root = registry.resolve("recursive")
    child = root.formulations["again"].blocks["next"]
    assert child.definition is root.definition
    assert child.path == "recursive.next"


def test_unused_alternatives_need_not_resolve():
    registry = BlockRegistry()
    registry.get("heat_pump").formulations["cycle"].blocks[
        "compressor"
    ].block = "absent"
    root = registry.resolve("heat_pump_flowsheet").formulations["flowsheet"].blocks["heat_pump"]
    assert set(root.formulations["aggregate"].blocks) == {
        "cop_model", "source_inlet_state", "source_outlet_state",
        "sink_inlet_state", "sink_outlet_state", "power_model",
    }
    assert root.formulations["aggregate"].blocks["cop_model"].id == "prescribed_cop"
    with pytest.raises(ValueError, match="Unknown model"):
        root.formulations["cycle"].blocks


def test_interface_errors_are_available_without_conversion():
    registry = BlockRegistry()
    registry.get("water_property_package").structs["state"].direction = "output"
    with pytest.raises(ValueError, match="incompatible required struct"):
        registry.resolve("water_state_block").formulations["evaluate"].blocks


def test_unknown_generic_parameter_is_reported_without_conversion():
    registry = BlockRegistry()
    registry.get("water_state_block").formulations["evaluate"].blocks["states"] = (
        ConcreteBlockReference.model_validate(
            {
                "block": "state_block",
                "block_arguments": {"FluidProperties": {"block_argument": "Missing"}},
            }
        )
    )
    with pytest.raises(ValueError, match="unknown block argument"):
        registry.resolve("water_state_block").formulations["evaluate"].blocks


def test_fresh_views_see_definition_edits():
    registry = BlockRegistry()
    before = registry.resolve("water_state_block").formulations["evaluate"].blocks
    registry.get("water_state_block").formulations["evaluate"].blocks.clear()
    assert "states" in before
    assert registry.resolve("water_state_block").formulations["evaluate"].blocks == {}
