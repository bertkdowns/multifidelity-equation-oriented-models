"""Model catalogs contain formulation choices without model IDs."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from multifidelity.model_language import ModelCatalog, FormulationSelection

EXAMPLES = Path(__file__).parents[1] / "examples/model_language"


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.json")), ids=lambda p: p.stem)
def test_existing_model_catalog_examples_parse_and_round_trip(path):
    catalog = ModelCatalog.load_json(path)
    assert ModelCatalog.from_json(catalog.model_dump_json()) == catalog


def test_recursive_selections_can_be_navigated():
    catalog = ModelCatalog.load_json(EXAMPLES / "water_state_block_evaluate.json")
    inlet = catalog.subblocks["states"].subblocks["fluid"]
    assert isinstance(inlet, FormulationSelection)
    assert inlet.formulation == "constant_properties"
    assert set(inlet.subblocks) == {"water"}
    assert inlet.subblocks["water"].formulation == "constant_properties"
    assert inlet.subblocks["water"].subblocks == {}


@pytest.mark.parametrize("catalog", [
    {},
    {"block": "water_state", "formulation": "constant_properties"},
    {"formulation": "constant_properties", "values": {}},
    {"formulation": "evaluate", "subblocks": {"child": {}}},
    {"formulation": "evaluate", "subblocks": {"bad.name": {"formulation": "evaluate"}}},
    {"formulation": "evaluate", "subblocks": {"child": {
        "block": "water_state", "formulation": "constant_properties",
    }}},
])
def test_incomplete_or_malformed_selection_shapes_fail(catalog):
    with pytest.raises(ValidationError):
        ModelCatalog.model_validate(catalog)


def test_catalog_can_be_passed_directly_to_numerical_builder():
    from multifidelity.model_language import build_model

    catalog = ModelCatalog(formulation="isenthalpic")
    model = build_model("valve", catalog)
    assert model.fs.root.structs.inlet.pressure.is_indexed()
    assert not model.fs.root.structs.inlet.pressure[model.fs.time.first()].fixed


@pytest.mark.parametrize("operation", ["build_model", "required_inputs", "required_initial_values"])
@pytest.mark.parametrize("source", ["dictionary", "file"])
def test_all_operations_validate_catalog_shape_consistently(tmp_path, operation, source):
    import json
    import multifidelity.model_language as language

    catalog = {"formulation": "isenthalpic", "unexpected": True}
    if source == "file":
        path = tmp_path / "model_selection.json"
        path.write_text(json.dumps(catalog))
        catalog = path
    with pytest.raises(ValidationError, match="unexpected"):
        getattr(language, operation)("valve", catalog)


@pytest.mark.parametrize("change", ["unknown_formulation", "missing_child", "extra_child"])
def test_selected_hierarchy_errors_are_identical_for_all_operations(change):
    from multifidelity.model_language import build_model, required_inputs, required_initial_values

    catalog = ModelCatalog.load_json(EXAMPLES / "water_state_block_evaluate.json")
    states = catalog.subblocks["states"]
    if change == "unknown_formulation":
        states.subblocks["fluid"].formulation = "absent"
    elif change == "missing_child":
        del states.subblocks["fluid"]
    else:
        states.subblocks["other"] = states.subblocks["fluid"]
    errors = []
    for operation in (build_model, required_inputs, required_initial_values):
        with pytest.raises(ValueError) as error:
            operation("water_state_block", catalog)
        errors.append(str(error.value))
    assert errors[0] == errors[1] == errors[2]
    assert "water_state_block.states" in errors[0]


def test_finite_recursive_selection_ignores_unselected_broken_alternatives():
    from multifidelity.model_language import (
        BlockLibrary, BlockCatalog, build_model, required_inputs, required_initial_values,
    )

    library = BlockLibrary()
    library.blocks["recursive"] = BlockCatalog.model_validate({
        "id": "recursive", "structs": {}, "formulations": {
            "leaf": {},
            "again": {"blocks": {"next": {"block": "recursive"}}},
            "broken": {"blocks": {"missing": {"block": "does_not_exist"}}},
        },
    })
    catalog = ModelCatalog.model_validate({
        "formulation": "again", "subblocks": {"next": {"formulation": "leaf"}},
    })
    model = build_model("recursive", catalog, library=library)
    assert set(model.fs.root.formulation.blocks.component_map()) == {"next"}
    assert required_inputs("recursive", catalog, library=library) == {}
    assert required_initial_values("recursive", catalog, library=library) == {}
