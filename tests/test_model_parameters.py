"""Parameter choices apply evidence atomically to selected numerical objects."""

from pathlib import Path

import pytest
from pydantic import ValidationError
from pyomo.environ import ConcreteModel, TransformationFactory, value
from pyomo.util.check_units import assert_units_consistent

from multifidelity.model_language import (
    ResourceCatalog, BlockLibrary, BlockCatalog, ParameterCatalog,
    apply_parameters, build_model, get_variable,
)


EXAMPLE = Path(__file__).parents[1] / "examples/parameters"


def valve():
    return build_model("valve", {"formulation": "isenthalpic"})


def resources(path="inlet.pressure", **changes):
    return ResourceCatalog([{
        "tag": "reading", "resource_type": "sensor_reading",
        "variable_path": path, "value": 200, "unit": "kPa", "trust_rank": 10,
        "standard_deviation": 0.5, **changes,
    }])


def catalog(record_tag="reading"):
    return {"parameters": [record_tag]}


def test_catalog_round_trip_and_minimal_shape():
    spec = ParameterCatalog.load_json(EXAMPLE / "parameters.json")
    assert ParameterCatalog.from_json(spec.model_dump_json()) == spec
    assert set(spec.model_dump()) == {"parameters", "replacements", "initial_values"}
    assert spec.parameters[0] == "inlet_flow"
    with pytest.raises(ValidationError):
        spec.parameters = ("other",)



@pytest.mark.parametrize("data", [
    {"parameters": [{"variable_path": "inlet.pressure"}]},
    {"parameters": [{"variable_path": "", "resources_record_tag": "reading"}]},
    {"parameters": [{"resources_record_tag": ""}]},
    {"parameters": [1]},
    dict(catalog(), structural_status="complete"),
    {"parameters": catalog()["parameters"] * 2},
])
def test_invalid_catalog_shapes(data):
    with pytest.raises(ValidationError):
        ParameterCatalog.model_validate(data)


def test_application_converts_and_fixes_without_changing_resources():
    model = valve()
    pressure = get_variable(model, "inlet.pressure")[0]
    pressure.set_value(42)
    table = resources()
    assert apply_parameters(model, catalog(), table) is None
    assert pressure.fixed and pressure.value == 200000
    assert table.get("reading").unit == "kPa"
    assert table.get("reading").standard_deviation == 0.5
    assert not model.fs.root.structs.outlet.pressure[0].fixed
    assert_units_consistent(model)


@pytest.mark.parametrize("path,record_tag,changes,error", [
    ("missing.pressure", "reading", {}, "Unknown model variable"),
    ("inlet.pressure", "absent", {}, "Unknown resource record"),
    ("inlet.pressure", "reading", {"unit": "kg"}, "inlet.pressure"),
    ("inlet.pressure", "reading", {"unit": "not_a_unit"}, "inlet.pressure"),
    ("inlet.pressure", "reading", {"type": "series", "value": [1, 2]}, "shape"),
])
def test_invalid_context_does_not_change_model(path, record_tag, changes, error):
    model = valve()
    variables = [v for component in model._model_language_variables.values()
                 for v in component.values()]
    before = [(v.value, v.fixed) for v in variables]
    with pytest.raises(ValueError, match=error):
        apply_parameters(model, catalog(record_tag), resources(path, **changes))
    assert [(v.value, v.fixed) for v in variables] == before


def test_all_entries_validate_before_any_values_change():
    model = valve()
    pressure = get_variable(model, "inlet.pressure")[0]
    pressure.set_value(123)
    spec = catalog()
    spec["parameters"] += catalog("missing")["parameters"]
    table = resources()
    missing = table.get("reading").model_copy(update={"tag": "missing", "variable_path": "missing.variable"})
    table.add(missing)
    with pytest.raises(ValueError, match="Unknown model variable"):
        apply_parameters(model, spec, table)
    assert pressure.value == 123 and not pressure.fixed


def test_bounds_and_existing_fixations_are_rejected_without_overwriting():
    model = valve()
    pressure = get_variable(model, "inlet.pressure")[0]
    pressure.set_value(123)
    pressure.setub(150000)
    with pytest.raises(ValueError, match="outside variable bounds"):
        apply_parameters(model, catalog(), resources())
    assert pressure.value == 123 and not pressure.fixed
    pressure.setub(None)
    pressure.fix(100000)
    with pytest.raises(ValueError, match="already fixed"):
        apply_parameters(model, catalog(), resources())
    assert pressure.value == 100000 and pressure.fixed


def test_selected_child_paths_and_cloned_models():
    library = BlockLibrary()
    library.blocks["wrapper"] = BlockCatalog.model_validate({
        "id": "wrapper", "structs": {}, "domains": {"time": {"kind": "time"}},
        "formulations": {"pair": {"blocks": {
            name: {"block": "valve", "domain_bindings": {"time": "time"}}
            for name in ("first", "second")
        }}},
    })
    model = build_model("wrapper", {
         "formulation": "pair", "subblocks": {
            name: {"formulation": "isenthalpic"} for name in ("first", "second")
        },
    }, library=library)
    cloned = model.clone()
    path = "second.inlet.pressure"
    apply_parameters(cloned, catalog(), resources(path))
    assert cloned.fs.root.formulation.blocks.second.structs.inlet.pressure[0].fixed
    assert not cloned.fs.root.formulation.blocks.first.structs.inlet.pressure[0].fixed
    assert not model.fs.root.formulation.blocks.second.structs.inlet.pressure[0].fixed


def test_constants_and_series_use_final_grid_and_scalar_variables():
    model = build_model("tank_flowsheet", "examples/model_language/tank_mixed.json",
                        mode="dynamic", domain_values={"time": [0, 60]})
    TransformationFactory("dae.finite_difference").apply_to(
        model, wrt=model.fs.time, nfe=2, scheme="BACKWARD",
    )
    path = "tank.inlet.enthalpy"
    apply_parameters(model, catalog(), resources(
        path, type="series", value=[30, 35, 40], unit="J/kg",
    ))
    assert list(model.fs.root.formulation.blocks.tank.structs.inlet.enthalpy) == [0, 30, 60]
    assert [v.value for v in model.fs.root.formulation.blocks.tank.structs.inlet.enthalpy.values()] == [30, 35, 40]
    assert all(v.fixed for v in model.fs.root.formulation.blocks.tank.structs.inlet.enthalpy.values())
    path = "tank.parameters.area"
    apply_parameters(model, catalog(), resources(path, value=2, unit="m**2"))
    assert model.fs.root.formulation.blocks.tank.structs.parameters.area.value == 2
    assert model.fs.root.formulation.blocks.tank.structs.parameters.area.fixed
    path = "tank.inlet.flow"
    apply_parameters(model, catalog(), resources(path, value=3, unit="kg/s"))
    assert all(v.fixed and value(v) == 3 for v in model.fs.root.formulation.blocks.tank.structs.inlet.flow.values())



def test_unregistered_models_and_empty_catalogs():
    with pytest.raises(ValueError, match="constructed by"):
        apply_parameters(ConcreteModel(), catalog(), resources())
    assert apply_parameters(valve(), {"parameters": []}, resources()) is None


def test_example_fully_specifies_and_solves(solver):
    from examples.parameters.run import run
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
    library = BlockLibrary()
    library.blocks["grid"] = BlockCatalog.model_validate({
        "id": "grid", "domains": {"time": {"kind": "time"}, "cells": {"kind": "discrete"}},
        "structs": {"feed": {"direction": "input", "variables": {
            "flow": {"unit": "g/s", "dimensions": ["cells", "time"]},
        }}},
        "formulations": {"specified": {}},
    })
    model = build_model("grid", {"formulation": "specified"},
                        library=library, domain_values={"cells": ["b", "a"], "time": [0, 10]})
    path = "feed.flow"
    apply_parameters(model, catalog(), resources(
        path, type="series", value=[[1, 2], [3, 4]], unit="kg/s",
    ))
    assert [(index, v.value) for index, v in model.fs.root.structs.feed.flow.items()] == [
        (("b", 0), 1000), (("b", 10), 2000),
        (("a", 0), 3000), (("a", 10), 4000),
    ]


def test_late_grid_conflict_preserves_all_previous_values():
    model = build_model("valve", {"formulation": "isenthalpic"},
                        domain_values={"time": [0, 10]})
    pressure = model.fs.root.structs.inlet.pressure
    pressure[0].set_value(10)
    pressure[10].set_value(20)
    pressure[10].setub(150000)
    with pytest.raises(ValueError, match="outside variable bounds"):
        apply_parameters(model, catalog(), resources())
    assert [v.value for v in pressure.values()] == [10, 20]
    assert all(not v.fixed for v in pressure.values())


def test_unexpected_fix_failure_rolls_back_prior_writes(monkeypatch):
    model = build_model("valve", {"formulation": "isenthalpic"},
                        domain_values={"time": [0, 10]})
    pressure = model.fs.root.structs.inlet.pressure
    pressure[0].set_value(10)
    pressure[10].set_value(20)
    original_fix = type(pressure[0]).fix

    def fail_second(variable, *args, **kwargs):
        if variable is pressure[10]:
            raise RuntimeError("backend failure")
        return original_fix(variable, *args, **kwargs)

    monkeypatch.setattr(type(pressure[0]), "fix", fail_second)
    with pytest.raises(RuntimeError, match="backend failure"):
        apply_parameters(model, catalog(), resources())
    assert pressure[0].value == 10 and not pressure[0].fixed
    assert pressure[10].value == 20 and not pressure[10].fixed


def test_different_records_for_same_variable_are_rejected_atomically():
    model = valve()
    pressure = get_variable(model, "inlet.pressure")[0]
    pressure.set_value(123)
    table = resources()
    table.add(table.get("reading").model_copy(update={"tag": "fallback", "value": 190}))
    spec = ParameterCatalog.model_validate({"parameters": [
        "reading", "fallback",
    ]})
    with pytest.raises(ValueError, match="Multiple resource records specify variable"):
        apply_parameters(model, spec, table)
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
    assert ParameterCatalog().parameters == ()
    assert ParameterCatalog().initial_values == ()
    catalog = ParameterCatalog(initial_values=["start"])
    assert ParameterCatalog.from_json(catalog.model_dump_json()) == catalog
    assert catalog.model_dump(mode="json") == {
        "parameters": [], "replacements": {}, "initial_values": ["start"],
    }


@pytest.mark.parametrize("data", [
    {"initial_values": [""]},
    {"initial_values": [1]},
    {"initial_values": ["start", "start"]},
    {"parameters": ["start"], "initial_values": ["start"]},
])
def test_invalid_initial_record_selections(data):
    with pytest.raises(ValidationError):
        ParameterCatalog.model_validate(data)


def dynamic_tank():
    return build_model("tank_flowsheet", "examples/model_language/tank_mixed.json", mode="dynamic",
                       domain_values={"time": [5, 65]})



def test_operating_and_initial_values_apply_together_on_final_grid():
    model = dynamic_tank()
    TransformationFactory("dae.finite_difference").apply_to(
        model, wrt=model.fs.time, nfe=2, scheme="BACKWARD",
    )
    table = resources("tank.inlet.flow", value=2, unit="kg/s")
    table.add({**table.get("reading").model_dump(), "tag": "start",
               "variable_path": "tank.inventory.level", "value": 100, "unit": "cm"})
    apply_parameters(model, {
        "parameters": ["reading"], "initial_values": ["start"],
    }, table)
    assert list(model.fs.time) == [5, 35, 65]
    assert all(v.fixed and value(v) == 2 for v in get_variable(model, "tank.inlet.flow").values())
    level = get_variable(model, "tank.inventory.level")
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
    flow = get_variable(model, "tank.inlet.flow")
    flow[5].set_value(42)
    table = resources("tank.inlet.flow", value=2, unit="kg/s")
    table.add({**table.get("reading").model_dump(), "tag": "start",
               "variable_path": "tank." + initial_path, "value": initial_value, "unit": initial_unit})
    with pytest.raises(ValueError, match=error):
        apply_parameters(model, {
            "parameters": ["reading"], "initial_values": ["start"],
        }, table)
    assert flow[5].value == 42 and not flow[5].fixed
    assert flow[65].value is None and not flow[65].fixed
    assert all(not v.fixed for component in model._model_language_variables.values()
               for v in component.values())



def test_initial_values_reject_steady_models_and_overlapping_families():
    with pytest.raises(ValueError, match="only in dynamic mode"):
        apply_parameters(valve(), {"initial_values": ["reading"]}, resources())
    model = dynamic_tank()
    table = resources("tank.inventory.level", value=1, unit="m")
    table.add({**table.get("reading").model_dump(), "tag": "start"})
    with pytest.raises(ValueError, match="Multiple resource records"):
        apply_parameters(model, {
            "parameters": ["reading"], "initial_values": ["start"],
        }, table)
    assert all(not v.fixed and v.value is None
               for v in get_variable(model, "tank.inventory.level").values())



@pytest.mark.parametrize("dimensions", [["time", "cells"], ["cells", "time"],
                                         ["cells", "time", "bands"]])
@pytest.mark.parametrize("kind", ["constant", "series"])
def test_initial_profiles_keep_non_time_axes_and_convert_units(dimensions, kind):
    library = BlockLibrary()
    domain_values = {"time": [0, 10], "cells": ["a", "b"]}
    domains = {"time": {"kind": "time"}, "cells": {"kind": "discrete"}}
    if "bands" in dimensions:
        domain_values["bands"] = ["x", "y"]
        domains["bands"] = {"kind": "discrete"}
    library.blocks["profile"] = BlockCatalog.model_validate({
        "id": "profile", "domains": domains, "structs": {
            "state": {"direction": "input", "variables": {
                "height": {"unit": "m", "dimensions": dimensions},
            }},
        }, "formulations": {"given": {}},
    })
    model = build_model("profile", {"formulation": "given"}, library=library,
                        mode="dynamic", domain_values=domain_values)
    profile = (100 if kind == "constant" else [[100, 200], [300, 400]]
               if "bands" in dimensions else [100, 300])
    table = resources("state.height", value=profile, unit="cm", type=kind)
    apply_parameters(model, {"initial_values": ["reading"]}, table)
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
        build_model("tank_flowsheet", "examples/model_language/tank_mixed.json", initial_values=[])
    model = dynamic_tank()
    assert all(not v.fixed
               for component in model._model_language_variables.values()
               for v in component.values())
