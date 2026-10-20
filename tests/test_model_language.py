"""Construction contracts for the declarative model language; no solver needed."""

import json

import pytest
from pyomo.environ import Var, value
from pyomo.core.base.units_container import UnitsError
from pyomo.util.check_units import assert_units_consistent

from multifidelity.model_language import Library, build_model


def select(library, model, relationship=None):
    definition = library.get(model)
    relationship = relationship or next(iter(definition["relationships"]))
    return {
        "model": model,
        "relationship": relationship,
        "submodels": {
            name: select(library, ref["model"])
            for name, ref in definition["relationships"][relationship]["models"].items()
        },
    }


def test_every_bundled_relationship_builds_without_solver():
    library = Library()
    for name, definition in library.models.items():
        for relationship in definition["relationships"]:
            if name == "milk_evaporator" and relationship == "aggregate":
                # This documented scaffold deliberately lacks physical closures.
                with pytest.raises(ValueError, match="missing output determinations"):
                    build_model(
                        name, select(library, name, relationship), library=library
                    )
                continue
            model = build_model(
                name, select(library, name, relationship), library=library
            )
            assert_units_consistent(model)
            assert all(not v.fixed for v in model.component_data_objects(Var))
            assert all(v.value is None for v in model.component_data_objects(Var))


def test_reused_definition_has_distinct_occurrences_and_connection_equations(tmp_path):
    library = Library()
    selection = select(library, "heat_pump", "cycle")
    path = tmp_path / "implementation.json"
    path.write_text(json.dumps(selection))
    model = build_model("heat_pump", path, library=library)
    parts = model.fs.root.relationship.models
    a, b = (
        parts.condenser.structs.hot_inlet.flow,
        parts.subcooler.structs.hot_inlet.flow,
    )
    assert a is not b
    a.set_value(3)
    assert b.value is None
    equation = model.fs.root.relationship.connections.link_2.flow
    parts.condenser.structs.hot_outlet.flow.set_value(3)
    b.set_value(2)
    assert abs(value(equation.body)) == 1


@pytest.mark.parametrize("change", ["missing", "extra", "unknown"])
def test_incomplete_or_invalid_selections_fail(change):
    library = Library()
    selection = select(library, "heat_pump", "cycle")
    if change == "missing":
        del selection["submodels"]["compressor"]
    elif change == "extra":
        selection["submodels"]["unused"] = {}
    else:
        selection["submodels"]["compressor"]["relationship"] = "nonexistent"
    with pytest.raises(ValueError):
        build_model("heat_pump", selection, library=library)


@pytest.mark.parametrize(
    "expression",
    [
        '__import__("os").getcwd()',
        "compressor.inlet.flow",
        "inlet.__class__",
    ],
)
def test_expression_language_rejects_execution_and_out_of_scope_references(expression):
    library = Library()
    library.models["valve"]["relationships"]["isenthalpic"]["constraints"]["bad"] = {
        "lhs": "outlet.flow",
        "rhs": expression,
    }
    with pytest.raises(ValueError):
        build_model("valve", select(library, "valve"), library=library)


def test_unselected_relationship_is_not_loaded():
    library = Library()
    library.models["heat_pump"]["relationships"]["cycle"]["models"]["compressor"][
        "model"
    ] = "absent"
    model = build_model(
        "heat_pump", select(library, "heat_pump", "aggregate"), library=library
    )
    assert len(list(model.fs.root.relationship.models.component_objects())) == 0


def test_only_selected_child_interface_is_accessible():
    library = Library()
    library.models["heat_pump"]["relationships"]["cycle"]["constraints"]["bad"] = {
        "lhs": "performance.heating_duty",
        "rhs": "compressor.hidden.inputs.work",
    }
    with pytest.raises(ValueError, match="inaccessible"):
        build_model("heat_pump", select(library, "heat_pump", "cycle"), library=library)


@pytest.mark.parametrize("change", ["fields", "direction", "units"])
def test_incompatible_connections_fail(change):
    library = Library()
    inlet = library.models["valve"]["structs"]["inlet"]
    if change == "fields":
        del inlet["variables"]["enthalpy"]
    elif change == "direction":
        inlet["direction"] = "output"
    else:
        inlet["variables"]["flow"]["unit"] = "K"
    with pytest.raises(UnitsError if change == "units" else ValueError):
        build_model("source_loop", select(library, "source_loop"), library=library)


def test_library_rejects_duplicate_ids(tmp_path):
    document = Library().get("valve")
    for name in ["a", "b"]:
        (tmp_path / f"{name}.json").write_text(json.dumps(document))
    with pytest.raises(ValueError, match="Duplicate"):
        Library(tmp_path)


def test_missing_outputs_are_listed():
    library = Library()
    constraints = library.models["valve"]["relationships"]["isenthalpic"]["constraints"]
    del constraints["eq_1"]
    del constraints["eq_2"]
    with pytest.raises(
        ValueError,
        match=r"valve.isenthalpic: missing output determinations: outlet.enthalpy, outlet.flow",
    ):
        build_model("valve", select(library, "valve"), library=library)


def test_duplicate_constraints_name_both_sources():
    library = Library()
    constraints = library.models["valve"]["relationships"]["isenthalpic"]["constraints"]
    constraints["another_flow"] = dict(constraints["eq_1"])
    with pytest.raises(
        ValueError, match=r"duplicate determination.*outlet.flow.*eq_1.*another_flow"
    ):
        build_model("valve", select(library, "valve"), library=library)


@pytest.mark.parametrize("kind", ["connection", "constraint"])
def test_connections_share_determination_namespace(kind):
    library = Library()
    relationship = library.models["heat_pump"]["relationships"]["cycle"]
    if kind == "connection":
        relationship["connections"]["duplicate"] = dict(
            relationship["connections"]["link_1"]
        )
    else:
        relationship["constraints"]["duplicate"] = {
            "lhs": "condenser.hot_inlet.flow",
            "rhs": "compressor.outlet.flow",
            "determines": "condenser.hot_inlet.flow",
        }
    with pytest.raises(
        ValueError, match=r"duplicate determination.*condenser.hot_inlet.flow"
    ):
        build_model("heat_pump", select(library, "heat_pump", "cycle"), library=library)


@pytest.mark.parametrize(
    "target", [None, "inlet.flow", "missing.value", "outlet.pressure", ["outlet.flow"]]
)
def test_constraint_target_must_be_valid_and_occur_in_equation(target):
    library = Library()
    equation = library.models["valve"]["relationships"]["isenthalpic"]["constraints"][
        "eq_1"
    ]
    if target is None:
        equation.pop("determines")
    else:
        equation["determines"] = target
    with pytest.raises(ValueError, match="invalid target|does not occur"):
        build_model("valve", select(library, "valve"), library=library)


def test_child_output_cannot_be_determined_by_containing_relationship():
    library = Library()
    library.models["heat_pump"]["relationships"]["cycle"]["constraints"]["bad"] = {
        "lhs": "compressor.outlet.flow",
        "rhs": "compressor.inlet.flow",
        "determines": "compressor.outlet.flow",
    }
    with pytest.raises(ValueError, match="invalid target"):
        build_model("heat_pump", select(library, "heat_pump", "cycle"), library=library)


def test_incomplete_milk_scaffold_reports_exact_missing_outputs():
    library = Library()
    with pytest.raises(ValueError) as error:
        build_model(
            "milk_evaporator",
            select(library, "milk_evaporator", "aggregate"),
            library=library,
        )
    assert str(error.value).endswith(
        "milk_outlet.enthalpy, milk_outlet.flow, milk_outlet.pressure, water_outlet.pressure"
    )
