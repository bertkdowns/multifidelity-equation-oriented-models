"""Implementation documents contain relationship choices without model IDs."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from multifidelity.model_language import ImplementationDocument, ImplementationSelection

EXAMPLES = Path(__file__).parents[1] / "examples/model_language"


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.json")), ids=lambda p: p.stem)
def test_existing_implementation_examples_parse_and_round_trip(path):
    document = ImplementationDocument.load_json(path)
    assert ImplementationDocument.from_json(document.model_dump_json()) == document


def test_recursive_selections_can_be_navigated():
    document = ImplementationDocument.load_json(EXAMPLES / "water_state_block_evaluate.json")
    inlet = document.submodels["states"].submodels["fluid"]
    assert isinstance(inlet, ImplementationSelection)
    assert inlet.relationship == "constant_properties"
    assert set(inlet.submodels) == {"water"}
    assert inlet.submodels["water"].relationship == "constant_properties"
    assert inlet.submodels["water"].submodels == {}


@pytest.mark.parametrize("document", [
    {},
    {"model": "water_state", "relationship": "constant_properties"},
    {"relationship": "constant_properties", "values": {}},
    {"relationship": "evaluate", "submodels": {"child": {}}},
    {"relationship": "evaluate", "submodels": {"bad.name": {"relationship": "evaluate"}}},
    {"relationship": "evaluate", "submodels": {"child": {
        "model": "water_state", "relationship": "constant_properties",
    }}},
])
def test_incomplete_or_malformed_selection_shapes_fail(document):
    with pytest.raises(ValidationError):
        ImplementationDocument.model_validate(document)


def test_document_can_be_passed_directly_to_numerical_builder():
    from multifidelity.model_language import build_model

    document = ImplementationDocument(relationship="isenthalpic")
    model = build_model("valve", document)
    assert model.fs.root.structs.inlet.pressure.is_indexed()
    assert not model.fs.root.structs.inlet.pressure[model.fs.time.first()].fixed


@pytest.mark.parametrize("operation", ["build_model", "required_inputs", "required_initial_values"])
@pytest.mark.parametrize("source", ["dictionary", "file"])
def test_all_operations_validate_document_shape_consistently(tmp_path, operation, source):
    import json
    import multifidelity.model_language as language

    document = {"relationship": "isenthalpic", "unexpected": True}
    if source == "file":
        path = tmp_path / "implementation.json"
        path.write_text(json.dumps(document))
        document = path
    with pytest.raises(ValidationError, match="unexpected"):
        getattr(language, operation)("valve", document)


@pytest.mark.parametrize("change", ["unknown_relationship", "missing_child", "extra_child"])
def test_selected_hierarchy_errors_are_identical_for_all_operations(change):
    from multifidelity.model_language import build_model, required_inputs, required_initial_values

    document = ImplementationDocument.load_json(EXAMPLES / "water_state_block_evaluate.json")
    states = document.submodels["states"]
    if change == "unknown_relationship":
        states.submodels["fluid"].relationship = "absent"
    elif change == "missing_child":
        del states.submodels["fluid"]
    else:
        states.submodels["other"] = states.submodels["fluid"]
    errors = []
    for operation in (build_model, required_inputs, required_initial_values):
        with pytest.raises(ValueError) as error:
            operation("water_state_block", document)
        errors.append(str(error.value))
    assert errors[0] == errors[1] == errors[2]
    assert "water_state_block.states" in errors[0]


def test_finite_recursive_selection_ignores_unselected_broken_alternatives():
    from multifidelity.model_language import (
        Library, ModelDocument, build_model, required_inputs, required_initial_values,
    )

    library = Library()
    library.models["recursive"] = ModelDocument.model_validate({
        "id": "recursive", "structs": {}, "relationships": {
            "leaf": {},
            "again": {"models": {"next": {"model": "recursive"}}},
            "broken": {"models": {"missing": {"model": "does_not_exist"}}},
        },
    })
    document = ImplementationDocument.model_validate({
        "relationship": "again", "submodels": {"next": {"relationship": "leaf"}},
    })
    model = build_model("recursive", document, library=library)
    assert set(model.fs.root.relationship.models.component_map()) == {"next"}
    assert required_inputs("recursive", document, library=library) == {}
    assert required_initial_values("recursive", document, library=library) == {}
