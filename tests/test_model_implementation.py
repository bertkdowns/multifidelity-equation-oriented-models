"""Implementation documents express explicit recursive relationship selections."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from multifidelity.model_language.implementation import (
    Implementation,
    ImplementationSelection,
)


EXAMPLES = Path(__file__).parents[1] / "examples/model_language"


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.json")), ids=lambda p: p.stem)
def test_existing_implementation_examples_parse_and_round_trip(path):
    implementation = Implementation.model_validate_json(path.read_text())
    assert (
        Implementation.model_validate_json(
            implementation.model_dump_json(exclude_none=True)
        )
        == implementation
    )


def test_recursive_selections_can_be_navigated():
    implementation = Implementation.model_validate_json(
        (EXAMPLES / "water_property_pair_evaluate.json").read_text()
    )
    inlet = implementation.submodels["states"].submodels["inlet"]
    assert isinstance(inlet, ImplementationSelection)
    assert inlet.relationship == "constant_properties"
    assert inlet.model is None
    assert inlet.submodels == {}


@pytest.mark.parametrize(
    "document",
    [
        {"relationship": "evaluate"},
        {"model": "water_state"},
        {"model": "", "relationship": "constant_properties"},
        {"model": "water_state", "relationship": "constant_properties", "values": {}},
        {"model": "wrapper", "relationship": "evaluate", "submodels": {"child": {}}},
        {
            "model": "wrapper",
            "relationship": "evaluate",
            "submodels": {"bad.name": {"relationship": "evaluate"}},
        },
    ],
)
def test_incomplete_or_malformed_selection_shapes_fail(document):
    with pytest.raises(ValidationError):
        Implementation.model_validate(document)


def test_explicit_nested_model_is_preserved():
    selection = ImplementationSelection(
        model="water_state", relationship="constant_properties"
    )
    assert selection.model_dump(exclude_none=True)["model"] == "water_state"
