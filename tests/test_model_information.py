"""Information lookup retains alternatives without selecting specifications."""

import json

import pytest
from pydantic import ValidationError

from multifidelity.model_language.information import InformationRecord, InformationTable


def record(record_id="measurement", **changes):
    return {
        "id": record_id,
        "tag": "TT101",
        "information_type": "sensor_reading",
        "variable_path": "sink_inlet.temperature",
        "value": 323.15,
        "unit": "K",
        "trust_rank": 10,
        **changes,
    }


def test_load_json_add_and_lookup(tmp_path):
    path = tmp_path / "information.json"
    path.write_text(json.dumps([record()]))
    table = InformationTable.load_json(path)
    assert table.get("measurement").value == 323.15
    added = table.add(record("estimate", information_type="assumption", trust_rank=1))
    assert isinstance(added, InformationRecord)
    assert table.get("estimate") is added
    assert [r.id for r in table.records] == ["measurement", "estimate"]


def test_candidates_keep_all_alternatives_and_order_by_trust_then_id():
    table = InformationTable.from_json(
        json.dumps(
            [
                record("z", trust_rank=9),
                record("fallback", trust_rank=1),
                record("a", trust_rank=9),
                record("other", variable_path="source_inlet.temperature"),
            ]
        )
    )
    assert [r.id for r in table.candidates("sink_inlet.temperature")] == [
        "a",
        "z",
        "fallback",
    ]
    assert table.candidates("absent") == []
    assert [r.id for r in table.records] == ["z", "fallback", "a", "other"]


def test_duplicate_ids_rejected_without_overwriting():
    table = InformationTable([record()])
    with pytest.raises(ValueError, match="Duplicate"):
        table.add(record(value=999))
    assert table.get("measurement").value == 323.15
    with pytest.raises(ValueError, match="Duplicate"):
        InformationTable.from_json(json.dumps([record(), record()]))


def test_unknown_record_and_storage_isolation():
    table = InformationTable([record()])
    table.records.clear()
    assert table.get("measurement").id == "measurement"
    with pytest.raises(ValidationError):
        table.get("measurement").id = "changed"
    with pytest.raises(KeyError, match="Unknown information record"):
        table.get("absent")


@pytest.mark.parametrize(
    "kind",
    [
        "sensor_reading",
        "control_setpoint",
        "equipment_specification",
        "parameter",
        "assumption",
    ],
)
def test_all_information_types(kind):
    assert (
        InformationRecord.model_validate(record(information_type=kind)).information_type
        == kind
    )


def test_missing_and_zero_uncertainty_are_distinct():
    assert InformationRecord.model_validate(record()).standard_deviation is None
    assert (
        InformationRecord.model_validate(
            record(standard_deviation=0)
        ).standard_deviation
        == 0
    )
    assert (
        InformationRecord.model_validate(
            record(standard_deviation=0.2)
        ).standard_deviation
        == 0.2
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"trust_rank": 0},
        {"trust_rank": 11},
        {"trust_rank": 3.5},
        {"trust_rank": True},
        {"standard_deviation": -0.1},
        {"value": float("inf")},
        {"standard_deviation": float("nan")},
        {"information_type": "guess"},
        {"id": ""},
        {"variable_path": ""},
        {"unexpected": "field"},
    ],
)
def test_invalid_records_are_rejected(changes):
    table = InformationTable()
    with pytest.raises(ValidationError):
        table.add(record(**changes))
    assert table.records == []


@pytest.mark.parametrize("text", ["{}", '[{"id": "incomplete"}]', "not json"])
def test_invalid_json_batches_fail(text):
    with pytest.raises(ValidationError):
        InformationTable.from_json(text)
