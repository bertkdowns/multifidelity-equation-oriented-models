"""Information lookup retains alternatives without selecting specifications."""

import json

import pytest
from pydantic import ValidationError

from multifidelity.model_language.information import InformationRecord, InformationDocument


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
    table = InformationDocument.load_json(path)
    assert table.get("measurement").value == 323.15
    added = table.add(record("estimate", information_type="assumption", trust_rank=1))
    assert isinstance(added, InformationRecord)
    assert table.get("estimate") is added
    assert [r.id for r in table.records] == ["measurement", "estimate"]


def test_candidates_keep_all_alternatives_and_order_by_trust_then_id():
    table = InformationDocument.from_json(
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
    table = InformationDocument([record()])
    with pytest.raises(ValueError, match="Duplicate"):
        table.add(record(value=999))
    assert table.get("measurement").value == 323.15
    with pytest.raises(ValueError, match="Duplicate"):
        InformationDocument.from_json(json.dumps([record(), record()]))


def test_unknown_record_and_storage_isolation():
    table = InformationDocument([record()])
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
    table = InformationDocument()
    with pytest.raises(ValidationError):
        table.add(record(**changes))
    assert table.records == []


@pytest.mark.parametrize("text", ["{}", '[{"id": "incomplete"}]', "not json"])
def test_invalid_json_batches_fail(text):
    with pytest.raises(ValidationError):
        InformationDocument.from_json(text)


def test_constant_is_default_and_round_trips():
    parsed = InformationRecord.model_validate(record())
    assert parsed.type == 'constant'
    assert parsed.shape == ()
    assert InformationRecord.model_validate_json(parsed.model_dump_json()) == parsed
    assert parsed.model_dump(mode='json')['type'] == 'constant'


def test_series_records_keep_metadata_and_json_arrays():
    parsed = InformationRecord.model_validate(record(
        type='series', value=[303.15, 305.15, 310.15], standard_deviation=0.2,
    ))
    assert parsed.value == (303.15, 305.15, 310.15)
    assert parsed.shape == (3,)
    assert parsed.standard_deviation == 0.2
    assert json.loads(parsed.model_dump_json())['value'] == [303.15, 305.15, 310.15]
    assert InformationRecord.model_validate_json(parsed.model_dump_json()) == parsed


def test_ndarray_and_nested_arrays_are_copied_and_immutable():
    import numpy as np
    source = np.array([[1, 2, 3], [4, 5, 6]], dtype=float)
    parsed = InformationRecord.model_validate(record(type='series', value=source))
    source[0, 0] = -1
    assert parsed.shape == (2, 3)
    assert parsed.value == ((1, 2, 3), (4, 5, 6))
    with pytest.raises(TypeError):
        parsed.value[0][0] = 99
    dumped = parsed.model_dump(mode='json')
    dumped['value'][0][0] = 99
    assert parsed.value[0][0] == 1
    constant = InformationRecord.model_validate(record(value=np.array(3.0)))
    assert constant.value == 3


def test_input_lists_do_not_expose_mutable_record_storage():
    source = [[1, 2], [3, 4]]
    table = InformationDocument([record(type='series', value=source)])
    source[0][0] = 99
    assert table.get('measurement').value[0][0] == 1


@pytest.mark.parametrize('changes', [
    {'type': 'unknown'},
    {'type': 'constant', 'value': [1, 2]},
    {'type': 'series', 'value': 1},
    {'type': 'series', 'value': []},
    {'type': 'series', 'value': [[], []]},
    {'type': 'series', 'value': [[1, 2], [3]]},
    {'type': 'series', 'value': [1, [2]]},
    {'type': 'series', 'value': [1, float('nan')]},
    {'type': 'series', 'value': [[1, 2], [3, float('inf')]]},
    {'type': 'series', 'value': [True, False]},
    {'type': 'series', 'value': ['1', '2']},
    {'type': 'series', 'value': [None]},
    {'type': 'series', 'value': {'time': 1}},
    {'value': True},
    {'type': 'series', 'value': [1, 2], 'standard_deviation': [0.1, 0.2]},
])
def test_invalid_constant_and_series_records(changes):
    table = InformationDocument()
    with pytest.raises(ValidationError):
        table.add(record(**changes))
    assert table.records == []


def test_constant_and_series_are_alternatives_for_the_same_family():
    table = InformationDocument.from_json(json.dumps([
        record('fallback', type='constant', trust_rank=1),
        record('trajectory', type='series', value=[303, 305, 310], trust_rank=9),
    ]))
    assert [r.id for r in table.candidates('sink_inlet.temperature')] == ['trajectory', 'fallback']
    with pytest.raises(ValueError, match='Duplicate'):
        table.add(record('trajectory', type='series', value=[1, 2, 3]))
    assert table.get('trajectory').value == (303, 305, 310)


def test_explicit_shape_validation():
    constant = InformationRecord.model_validate(record())
    constant.validate_shape(())
    constant.validate_shape((2, 3))
    series = InformationRecord.model_validate(record(type='series', value=[[1, 2, 3], [4, 5, 6]]))
    series.validate_shape((2, 3))
    with pytest.raises(ValueError, match='does not match'):
        series.validate_shape((3, 2))
    with pytest.raises(ValueError, match='does not match'):
        series.validate_shape(())
    for shape in [(0,), (-1,), (True,), (1.5,)]:
        with pytest.raises(ValueError, match='positive integer'):
            constant.validate_shape(shape)


def test_values_for_scalar_and_final_dynamic_grid():
    from pyomo.environ import TransformationFactory
    from multifidelity.model_language import build_model

    model = build_model("tank_flowsheet", "examples/model_language/tank_mixed.json",
                        mode='dynamic', domain_values={'time': [0, 60]})
    scalar = model.fs.root.relationship.models.tank.structs.parameters.area
    inlet = model.fs.root.relationship.models.tank.structs.inlet.enthalpy
    constant = InformationRecord.model_validate(record(value=303.15))
    series = InformationRecord.model_validate(record(type='series', value=[303.15, 305.15, 310.15]))
    area = InformationRecord.model_validate(record(
        variable_path='tank.parameters.area', value=1, unit='m**2',
    ))
    assert area.values_for(scalar) == {None: 1}
    assert constant.values_for(inlet) == {0: 303.15, 60: 303.15}
    with pytest.raises(ValueError, match='does not match'):
        series.values_for(inlet)
    TransformationFactory('dae.finite_difference').apply_to(
        model, wrt=model.fs.time, nfe=2, scheme='BACKWARD',
    )
    assert series.values_for(inlet) == {0: 303.15, 30: 305.15, 60: 310.15}
    assert constant.values_for(inlet) == {0: 303.15, 30: 303.15, 60: 303.15}
    assert all(v.value is None and not v.fixed for v in inlet.values())
    assert scalar.value is None and not scalar.fixed
    with pytest.raises(ValueError, match='does not match'):
        series.values_for(scalar)



def test_values_for_respects_ordered_domain_axes_and_record_units():
    from pyomo.environ import ConcreteModel, Set, Var, units
    m = ConcreteModel()
    m.cells = Set(initialize=['b', 'a'], ordered=True)
    m.time = Set(initialize=[0, 10, 20], ordered=True)
    m.pressure = Var(m.cells, m.time, units=units.Pa)
    series = InformationRecord.model_validate(record(
        type='series', value=[[1, 2, 3], [4, 5, 6]], unit='kPa',
    ))
    assert series.values_for(m.pressure) == {
        ('b', 0): 1, ('b', 10): 2, ('b', 20): 3,
        ('a', 0): 4, ('a', 10): 5, ('a', 20): 6,
    }
    # This is evidence mapping, not a unit-converting specification operation.
    assert not m.pressure['b', 0].fixed
    assert m.pressure['b', 0].value is None


def test_values_for_rejects_ambiguous_index_domains():
    from pyomo.environ import ConcreteModel, Set, Var
    m = ConcreteModel()
    m.unordered = Set(initialize=[1, 2], ordered=False)
    m.pairs = Set(initialize=[(1, 2), (3, 4)], dimen=2)
    m.x = Var(m.unordered)
    m.y = Var(m.pairs)
    series = InformationRecord.model_validate(record(type='series', value=[1, 2]))
    for variable in (m.x, m.y):
        with pytest.raises(ValueError, match='ordered one-dimensional'):
            series.values_for(variable)
    constant = InformationRecord.model_validate(record(value=1))
    assert constant.values_for(m.x) == {1: 1, 2: 1}
    assert constant.values_for(m.y) == {(1, 2): 1, (3, 4): 1}


def test_information_document_is_pydantic_and_round_trips_as_an_array():
    from pydantic import BaseModel

    document = InformationDocument.model_validate([record()])
    assert isinstance(document, BaseModel)
    assert InformationDocument.from_json(document.model_dump_json()) == document
    assert document.model_dump(mode="json")[0]["id"] == "measurement"
    document.add(record("fallback", trust_rank=1))
    assert [r.id for r in document.records] == ["measurement", "fallback"]
    with pytest.raises(ValidationError, match="Duplicate"):
        document.root = (*document.root, document.root[0])
    assert [r.id for r in document.records] == ["measurement", "fallback"]
