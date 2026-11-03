"""Definition documents can be inspected without building solver components."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from multifidelity.model_language.definitions import Connection, ModelDocument, Relationship


MODELS = Path(__file__).parents[1] / "src/multifidelity/model_language/models"


@pytest.mark.parametrize("path", sorted(MODELS.glob("*.json")), ids=lambda p: p.stem)
def test_bundled_definitions_parse_and_round_trip(path):
    model = ModelDocument.model_validate_json(path.read_text())
    assert ModelDocument.model_validate(model.model_dump(by_alias=True)) == model
    assert model.id == path.stem


def test_definition_navigation_preserves_generic_references():
    model = ModelDocument.model_validate_json((MODELS / "state_block.json").read_text())
    assert model.structs["state"].variables["pressure"].unit == "Pa"
    assert (
        model.relationships["evaluate"].models["fluid"].model_parameter
        == "FluidProperties"
    )


@pytest.mark.parametrize(
    "reference",
    [
        {},
        {"model": "water_state", "model_parameter": "Fluid"},
        {"model_parameter": "Fluid", "model_arguments": {}},
    ],
)
def test_reference_kinds_are_exclusive(reference):
    with pytest.raises(ValidationError):
        Relationship(models={"state": reference})


def test_connections_keep_json_field_names():
    connection = Connection.model_validate({"from": "inlet", "to": "child.state"})
    assert connection.from_ == "inlet"
    assert connection.model_dump(by_alias=True) == {
        "from": "inlet",
        "to": "child.state",
    }


def test_misspelled_fields_and_missing_determines_are_rejected():
    with pytest.raises(ValidationError):
        Relationship(constaints={})
    with pytest.raises(ValidationError):
        Relationship(
            constraints={"pressure": {"lhs": "a.pressure", "rhs": "b.pressure"}}
        )
