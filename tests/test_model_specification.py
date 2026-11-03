"""Specification choices apply evidence atomically to selected numerical objects."""

from pathlib import Path

import pytest
from pydantic import ValidationError
from pyomo.environ import ConcreteModel, TransformationFactory, value
from pyomo.util.check_units import assert_units_consistent

from multifidelity.model_language import (
    InformationDocument, Library, ModelDocument, SpecificationDocument,
    apply_specification, build_model, get_variable,
)


EXAMPLE = Path(__file__).parents[1] / "examples/specification"


def valve():
    return build_model("valve", {"relationship": "isenthalpic"})


def information(path="inlet.pressure", **changes):
    return InformationDocument([{
        "id": "reading", "tag": "PT101", "information_type": "sensor_reading",
        "variable_path": path, "value": 200, "unit": "kPa", "trust_rank": 10,
        "standard_deviation": 0.5, **changes,
    }])


def document(record_id="reading"):
    return {"specifications": [record_id]}


def test_document_round_trip_and_minimal_shape():
    spec = SpecificationDocument.load_json(EXAMPLE / "specification.json")
    assert SpecificationDocument.from_json(spec.model_dump_json()) == spec
    assert set(spec.model_dump()) == {"specifications", "initial_values"}
    assert spec.specifications[0] == "inlet_flow"
    with pytest.raises(ValidationError):
        spec.specifications = ("other",)



@pytest.mark.parametrize("data", [
    {"specifications": [{"variable_path": "inlet.pressure"}]},
    {"specifications": [{"variable_path": "", "information_record_id": "reading"}]},
    {"specifications": [{"information_record_id": ""}]},
    {"specifications": [1]},
    dict(document(), structural_status="complete"),
    {"specifications": document()["specifications"] * 2},
])
def test_invalid_document_shapes(data):
    with pytest.raises(ValidationError):
        SpecificationDocument.model_validate(data)


def test_application_converts_and_fixes_without_changing_information():
    model = valve()
    pressure = get_variable(model, "inlet.pressure")[0]
    pressure.set_value(42)
    table = information()
    assert apply_specification(model, document(), table) is None
    assert pressure.fixed and pressure.value == 200000
    assert table.get("reading").unit == "kPa"
    assert table.get("reading").standard_deviation == 0.5
    assert not model.fs.root.structs.outlet.pressure[0].fixed
    assert_units_consistent(model)


@pytest.mark.parametrize("path,record_id,changes,error", [
    ("missing.pressure", "reading", {}, "Unknown model variable"),
    ("inlet.pressure", "absent", {}, "Unknown information record"),
    ("inlet.pressure", "reading", {"unit": "kg"}, "inlet.pressure"),
    ("inlet.pressure", "reading", {"unit": "not_a_unit"}, "inlet.pressure"),
    ("inlet.pressure", "reading", {"type": "series", "value": [1, 2]}, "shape"),
])
def test_invalid_context_does_not_change_model(path, record_id, changes, error):
    model = valve()
    with pytest.raises(ValueError, match=error):
        apply_specification(model, document(record_id), information(path, **changes))
    assert all(v.value is None and not v.fixed
               for component in model._model_language_variables.values()
               for v in component.values())


def test_all_entries_validate_before_any_values_change():
    model = valve()
    pressure = get_variable(model, "inlet.pressure")[0]
    pressure.set_value(123)
    spec = document()
    spec["specifications"] += document("missing")["specifications"]
    table = information()
    missing = table.get("reading").model_copy(update={"id": "missing", "variable_path": "missing.variable"})
    table.add(missing)
    with pytest.raises(ValueError, match="Unknown model variable"):
        apply_specification(model, spec, table)
    assert pressure.value == 123 and not pressure.fixed


def test_bounds_and_existing_fixations_are_rejected_without_overwriting():
    model = valve()
    pressure = get_variable(model, "inlet.pressure")[0]
    pressure.setub(150000)
    with pytest.raises(ValueError, match="outside variable bounds"):
        apply_specification(model, document(), information())
    assert pressure.value is None and not pressure.fixed
    pressure.setub(None)
    pressure.fix(100000)
    with pytest.raises(ValueError, match="already fixed"):
        apply_specification(model, document(), information())
    assert pressure.value == 100000 and pressure.fixed


def test_selected_child_paths_and_cloned_models():
    library = Library()
    library.models["wrapper"] = ModelDocument.model_validate({
        "id": "wrapper", "structs": {}, "domains": {"time": {"kind": "time"}},
        "relationships": {"pair": {"models": {
            name: {"model": "valve", "domain_bindings": {"time": "time"}}
            for name in ("first", "second")
        }}},
    })
    model = build_model("wrapper", {
         "relationship": "pair", "submodels": {
            name: {"relationship": "isenthalpic"} for name in ("first", "second")
        },
    }, library=library)
    cloned = model.clone()
    path = "second.inlet.pressure"
    apply_specification(cloned, document(), information(path))
    assert cloned.fs.root.relationship.models.second.structs.inlet.pressure[0].fixed
    assert not cloned.fs.root.relationship.models.first.structs.inlet.pressure[0].fixed
    assert not model.fs.root.relationship.models.second.structs.inlet.pressure[0].fixed


def test_constants_and_series_use_final_grid_and_scalar_variables():
    model = build_model("tank", {"relationship": "mixed"},
                        mode="dynamic", domain_values={"time": [0, 60]})
    TransformationFactory("dae.finite_difference").apply_to(
        model, wrt=model.fs.time, nfe=2, scheme="BACKWARD",
    )
    path = "inlet.temperature"
    apply_specification(model, document(), information(
        path, type="series", value=[30, 35, 40], unit="K",
    ))
    assert list(model.fs.root.structs.inlet.temperature) == [0, 30, 60]
    assert [v.value for v in model.fs.root.structs.inlet.temperature.values()] == [30, 35, 40]
    assert all(v.fixed for v in model.fs.root.structs.inlet.temperature.values())
    path = "parameters.area"
    apply_specification(model, document(), information(path, value=2, unit="m**2"))
    assert model.fs.root.structs.parameters.area.value == 2
    assert model.fs.root.structs.parameters.area.fixed
    path = "inlet.flow"
    apply_specification(model, document(), information(path, value=3, unit="kg/s"))
    assert all(v.fixed and value(v) == 3 for v in model.fs.root.structs.inlet.flow.values())


def test_unregistered_models_and_empty_documents():
    with pytest.raises(ValueError, match="constructed by"):
        apply_specification(ConcreteModel(), document(), information())
    assert apply_specification(valve(), {"specifications": []}, information()) is None


def test_example_fully_specifies_and_solves(solver):
    from examples.specification.run import run
    from idaes.core.util.model_statistics import degrees_of_freedom
    from pyomo.environ import assert_optimal_termination

    model, result, outputs = run(solver=solver)
    assert degrees_of_freedom(model) == 0
    assert_optimal_termination(result)
    assert outputs == pytest.approx({
        "flow_kg_per_s": 2, "pressure_Pa": 175000, "enthalpy_J_per_kg": 100000,
    })
    assert get_variable(model, "inlet.pressure")[0].value == 200000
    assert all(not v.fixed for v in model.fs.root.structs.outlet.pressure.values())


def test_multidimensional_series_convert_in_declared_axis_order():
    library = Library()
    library.models["grid"] = ModelDocument.model_validate({
        "id": "grid", "domains": {"time": {"kind": "time"}, "cells": {"kind": "discrete"}},
        "structs": {"feed": {"direction": "input", "variables": {
            "flow": {"unit": "g/s", "dimensions": ["cells", "time"]},
        }}},
        "relationships": {"specified": {}},
    })
    model = build_model("grid", {"relationship": "specified"},
                        library=library, domain_values={"cells": ["b", "a"], "time": [0, 10]})
    path = "feed.flow"
    apply_specification(model, document(), information(
        path, type="series", value=[[1, 2], [3, 4]], unit="kg/s",
    ))
    assert [(index, v.value) for index, v in model.fs.root.structs.feed.flow.items()] == [
        (("b", 0), 1000), (("b", 10), 2000),
        (("a", 0), 3000), (("a", 10), 4000),
    ]


def test_late_grid_conflict_preserves_all_previous_values():
    model = build_model("valve", {"relationship": "isenthalpic"},
                        domain_values={"time": [0, 10]})
    pressure = model.fs.root.structs.inlet.pressure
    pressure[0].set_value(10)
    pressure[10].set_value(20)
    pressure[10].setub(150000)
    with pytest.raises(ValueError, match="outside variable bounds"):
        apply_specification(model, document(), information())
    assert [v.value for v in pressure.values()] == [10, 20]
    assert all(not v.fixed for v in pressure.values())


def test_unexpected_fix_failure_rolls_back_prior_writes(monkeypatch):
    model = build_model("valve", {"relationship": "isenthalpic"},
                        domain_values={"time": [0, 10]})
    pressure = model.fs.root.structs.inlet.pressure
    pressure[0].set_value(10)
    original_fix = type(pressure[0]).fix

    def fail_second(variable, *args, **kwargs):
        if variable is pressure[10]:
            raise RuntimeError("backend failure")
        return original_fix(variable, *args, **kwargs)

    monkeypatch.setattr(type(pressure[0]), "fix", fail_second)
    with pytest.raises(RuntimeError, match="backend failure"):
        apply_specification(model, document(), information())
    assert pressure[0].value == 10 and not pressure[0].fixed
    assert pressure[10].value is None and not pressure[10].fixed


def test_different_records_for_same_variable_are_rejected_atomically():
    model = valve()
    pressure = get_variable(model, "inlet.pressure")[0]
    pressure.set_value(123)
    table = information()
    table.add(table.get("reading").model_copy(update={"id": "fallback", "value": 190}))
    spec = SpecificationDocument.model_validate({"specifications": [
        "reading", "fallback",
    ]})
    with pytest.raises(ValueError, match="Multiple information records specify variable"):
        apply_specification(model, spec, table)
    assert pressure.value == 123 and not pressure.fixed


def test_public_variable_lookup_returns_live_families_and_checks_context():
    model = valve()
    pressure = get_variable(model, "inlet.pressure")
    assert pressure is model.fs.root.structs.inlet.pressure
    with pytest.raises(ValueError, match="Unknown model variable"):
        get_variable(model, "missing.pressure")
    with pytest.raises(ValueError, match="constructed by"):
        get_variable(ConcreteModel(), "inlet.pressure")


def test_both_lists_default_to_empty_and_round_trip():
    assert SpecificationDocument().specifications == ()
    assert SpecificationDocument().initial_values == ()
    document = SpecificationDocument(initial_values=["start"])
    assert SpecificationDocument.from_json(document.model_dump_json()) == document
    assert document.model_dump(mode="json") == {
        "specifications": [], "initial_values": ["start"],
    }


@pytest.mark.parametrize("data", [
    {"initial_values": [""]},
    {"initial_values": [1]},
    {"initial_values": ["start", "start"]},
    {"specifications": ["start"], "initial_values": ["start"]},
])
def test_invalid_initial_record_selections(data):
    with pytest.raises(ValidationError):
        SpecificationDocument.model_validate(data)


def dynamic_tank():
    return build_model("tank", {"relationship": "mixed"}, mode="dynamic",
                       domain_values={"time": [5, 65]})


def test_operating_and_initial_values_apply_together_on_final_grid():
    model = dynamic_tank()
    TransformationFactory("dae.finite_difference").apply_to(
        model, wrt=model.fs.time, nfe=2, scheme="BACKWARD",
    )
    table = information("inlet.flow", value=2, unit="kg/s")
    table.add({**table.get("reading").model_dump(), "id": "start", "tag": "start",
               "variable_path": "inventory.level", "value": 100, "unit": "cm"})
    apply_specification(model, {
        "specifications": ["reading"], "initial_values": ["start"],
    }, table)
    assert list(model.fs.time) == [5, 35, 65]
    assert all(v.fixed and value(v) == 2 for v in get_variable(model, "inlet.flow").values())
    level = get_variable(model, "inventory.level")
    assert level[5].fixed and level[5].value == 1
    assert not level[35].fixed and level[35].value is None
    assert not level[65].fixed and level[65].value is None
    assert table.get("start").value == 100


@pytest.mark.parametrize("initial_path,initial_unit,initial_value,error", [
    ("missing.level", "m", 1, "Unknown model variable"),
    ("parameters.area", "m**2", 1, "time-indexed"),
    ("inventory.level", "m", -1, "outside variable bounds"),
    ("inventory.level", "kg", 1, "inventory.level"),
])
def test_invalid_initial_value_preserves_operating_values_and_guesses(
    initial_path, initial_unit, initial_value, error,
):
    model = dynamic_tank()
    flow = get_variable(model, "inlet.flow")
    flow[5].set_value(42)
    table = information("inlet.flow", value=2, unit="kg/s")
    table.add({**table.get("reading").model_dump(), "id": "start", "tag": "start",
               "variable_path": initial_path, "value": initial_value, "unit": initial_unit})
    with pytest.raises(ValueError, match=error):
        apply_specification(model, {
            "specifications": ["reading"], "initial_values": ["start"],
        }, table)
    assert flow[5].value == 42 and not flow[5].fixed
    assert flow[65].value is None and not flow[65].fixed
    assert all(not v.fixed for component in model._model_language_variables.values()
               for v in component.values())


def test_initial_values_reject_steady_models_and_overlapping_families():
    with pytest.raises(ValueError, match="only in dynamic mode"):
        apply_specification(valve(), {"initial_values": ["reading"]}, information())
    model = dynamic_tank()
    table = information("inventory.level", value=1, unit="m")
    table.add({**table.get("reading").model_dump(), "id": "start", "tag": "start"})
    with pytest.raises(ValueError, match="Multiple information records"):
        apply_specification(model, {
            "specifications": ["reading"], "initial_values": ["start"],
        }, table)
    assert all(not v.fixed and v.value is None
               for v in get_variable(model, "inventory.level").values())


@pytest.mark.parametrize("dimensions", [["time", "cells"], ["cells", "time"],
                                         ["cells", "time", "bands"]])
@pytest.mark.parametrize("kind", ["constant", "series"])
def test_initial_profiles_keep_non_time_axes_and_convert_units(dimensions, kind):
    library = Library()
    domain_values = {"time": [0, 10], "cells": ["a", "b"]}
    domains = {"time": {"kind": "time"}, "cells": {"kind": "discrete"}}
    if "bands" in dimensions:
        domain_values["bands"] = ["x", "y"]
        domains["bands"] = {"kind": "discrete"}
    library.models["profile"] = ModelDocument.model_validate({
        "id": "profile", "domains": domains, "structs": {
            "state": {"direction": "input", "variables": {
                "height": {"unit": "m", "dimensions": dimensions},
            }},
        }, "relationships": {"given": {}},
    })
    model = build_model("profile", {"relationship": "given"}, library=library,
                        mode="dynamic", domain_values=domain_values)
    profile = (100 if kind == "constant" else [[100, 200], [300, 400]]
               if "bands" in dimensions else [100, 300])
    table = information("state.height", value=profile, unit="cm", type=kind)
    apply_specification(model, {"initial_values": ["reading"]}, table)
    variable = get_variable(model, "state.height")
    initial_values = []
    for index, entry in variable.items():
        if index[dimensions.index("time")] == 0:
            assert entry.fixed
            initial_values.append(entry.value)
        else:
            assert not entry.fixed and entry.value is None
    expected = [1] * (4 if "bands" in dimensions else 2) if kind == "constant" else (
        [1, 2, 3, 4] if "bands" in dimensions else [1, 3]
    )
    assert initial_values == expected


def test_builder_no_longer_accepts_initial_values_and_leaves_all_values_free():
    with pytest.raises(TypeError, match="initial_values"):
        build_model("tank", {"relationship": "mixed"}, initial_values=[])
    model = dynamic_tank()
    assert all(not v.fixed and v.value is None
               for component in model._model_language_variables.values()
               for v in component.values())
