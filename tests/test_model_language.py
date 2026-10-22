"""Construction contracts for the declarative model language; no solver needed."""

import json
import pytest
from pyomo.environ import Var, value
from pyomo.core.base.units_container import UnitsError
from pyomo.util.check_units import assert_units_consistent
from multifidelity.model_language import Library, build_model
from multifidelity.model_language.definitions import (
    Model,
    Constraint,
    ConcreteModelReference,
    ParameterModelReference,
)


def select(library, model, relationship=None, parameters=None):
    parameters = parameters or {}
    definition = library.get(model)
    relationship = relationship or next(iter(definition.relationships))
    children = {}
    for name, ref in definition.relationships[relationship].models.items():
        if isinstance(ref, ParameterModelReference):
            child_model = parameters[ref.model_parameter]
            child_parameters = {}
        else:
            child_model = ref.model
            child_parameters = {
                key: arg.model
                if isinstance(arg, ConcreteModelReference)
                else parameters[arg.model_parameter]
                for key, arg in ref.model_arguments.items()
            }
        children[name] = select(library, child_model, parameters=child_parameters)
    return {"model": model, "relationship": relationship, "submodels": children}


def test_every_bundled_relationship_builds_without_solver():
    library = Library()
    for name, definition in library.models.items():
        if definition.model_parameters:
            continue
        for relationship in definition.relationships:
            if name == "milk_evaporator" and relationship == "aggregate":
                with pytest.raises(ValueError, match="missing output determinations"):
                    build_model(
                        name, select(library, name, relationship), library=library
                    )
                continue
            model = build_model(
                name, select(library, name, relationship), library=library
            )
            assert_units_consistent(model)
            assert all((not v.fixed for v in model.component_data_objects(Var)))
            assert all((v.value is None for v in model.component_data_objects(Var)))


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
    ['__import__("os").getcwd()', "compressor.inlet.flow", "inlet.__class__"],
)
def test_expression_language_rejects_execution_and_out_of_scope_references(expression):
    library = Library()
    library.models["valve"].relationships["isenthalpic"].constraints["bad"] = (
        Constraint.model_validate(
            {"lhs": "outlet.flow", "rhs": expression, "determines": "outlet.flow"}
        )
    )
    with pytest.raises(ValueError):
        build_model("valve", select(library, "valve"), library=library)


def test_unselected_relationship_is_not_loaded():
    library = Library()
    library.models["heat_pump"].relationships["cycle"].models[
        "compressor"
    ].model = "absent"
    model = build_model(
        "heat_pump", select(library, "heat_pump", "aggregate"), library=library
    )
    assert len(list(model.fs.root.relationship.models.component_objects())) == 0


def test_only_selected_child_interface_is_accessible():
    library = Library()
    library.models["heat_pump"].relationships["cycle"].constraints["bad"] = (
        Constraint.model_validate(
            {
                "lhs": "performance.heating_duty",
                "rhs": "compressor.hidden.inputs.work",
                "determines": "performance.heating_duty",
            }
        )
    )
    # Keep a single determination so this test isolates reference visibility.
    del library.models["heat_pump"].relationships["cycle"].constraints["eq_2"]
    with pytest.raises(ValueError, match="inaccessible"):
        build_model("heat_pump", select(library, "heat_pump", "cycle"), library=library)


@pytest.mark.parametrize("change", ["fields", "direction", "units"])
def test_incompatible_connections_fail(change):
    library = Library()
    inlet = library.models["valve"].structs["inlet"]
    if change == "fields":
        del inlet.variables["enthalpy"]
    elif change == "direction":
        inlet.direction = "output"
    else:
        inlet.variables["flow"].unit = "K"
    with pytest.raises(UnitsError if change == "units" else ValueError):
        build_model("source_loop", select(library, "source_loop"), library=library)


def test_library_rejects_duplicate_ids(tmp_path):
    document = Library().get("valve")
    for name in ["a", "b"]:
        (tmp_path / f"{name}.json").write_text(document.model_dump_json(by_alias=True))
    with pytest.raises(ValueError, match="Duplicate"):
        Library(tmp_path)


def test_missing_outputs_are_listed():
    library = Library()
    constraints = library.models["valve"].relationships["isenthalpic"].constraints
    del constraints["eq_1"]
    del constraints["eq_2"]
    with pytest.raises(
        ValueError,
        match="valve.isenthalpic: missing output determinations: outlet.enthalpy, outlet.flow",
    ):
        build_model("valve", select(library, "valve"), library=library)


def test_duplicate_constraints_name_both_sources():
    library = Library()
    constraints = library.models["valve"].relationships["isenthalpic"].constraints
    constraints["another_flow"] = constraints["eq_1"].model_copy()
    with pytest.raises(
        ValueError, match="duplicate determination.*outlet.flow.*eq_1.*another_flow"
    ):
        build_model("valve", select(library, "valve"), library=library)


@pytest.mark.parametrize("kind", ["connection", "constraint"])
def test_connections_share_determination_namespace(kind):
    library = Library()
    relationship = library.models["heat_pump"].relationships["cycle"]
    if kind == "connection":
        relationship.connections["duplicate"] = relationship.connections[
            "link_1"
        ].model_copy()
    else:
        relationship.constraints["duplicate"] = Constraint.model_validate(
            {
                "lhs": "condenser.hot_inlet.flow",
                "rhs": "compressor.outlet.flow",
                "determines": "condenser.hot_inlet.flow",
            }
        )
    with pytest.raises(
        ValueError, match="duplicate determination.*condenser.hot_inlet.flow"
    ):
        build_model("heat_pump", select(library, "heat_pump", "cycle"), library=library)


@pytest.mark.parametrize("target", ["inlet.flow", "missing.value", "outlet.pressure"])
def test_constraint_target_must_be_valid_and_occur_in_equation(target):
    library = Library()
    equation = library.models["valve"].relationships["isenthalpic"].constraints["eq_1"]
    equation.determines = target
    if target == "outlet.pressure":
        # Swap targets to retain complete coverage without duplicate targets.
        library.models["valve"].relationships["isenthalpic"].constraints[
            "eq_3"
        ].determines = "outlet.flow"
    with pytest.raises(ValueError, match="invalid target|does not occur"):
        build_model("valve", select(library, "valve"), library=library)


def test_child_output_cannot_be_determined_by_containing_relationship():
    library = Library()
    library.models["heat_pump"].relationships["cycle"].constraints["bad"] = (
        Constraint.model_validate(
            {
                "lhs": "compressor.outlet.flow",
                "rhs": "compressor.inlet.flow",
                "determines": "compressor.outlet.flow",
            }
        )
    )
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


@pytest.mark.parametrize("temperature,pressure", [(298.15, 101325), (308.15, 201325)])
def test_water_state_property_equations(temperature, pressure):
    library = Library()
    model = build_model("water_state", select(library, "water_state"), library=library)
    root = model.fs.root
    root.structs.state.temperature.set_value(temperature)
    root.structs.state.pressure.set_value(pressure)
    coefficients = {
        "reference_temperature": 298.15,
        "reference_pressure": 101325,
        "reference_enthalpy": 104920.1198085,
        "heat_capacity": 4180,
        "density": 997,
        "viscosity": 0.00089,
    }
    for name, number in coefficients.items():
        getattr(root.structs.parameters, name).set_value(number)
    expected = {
        "enthalpy": coefficients["reference_enthalpy"]
        + 4180 * (temperature - 298.15)
        + (pressure - 101325) / 997,
        "density": 997,
        "heat_capacity": 4180,
        "viscosity": 0.00089,
    }
    for name, number in expected.items():
        variable = getattr(root.structs.properties, name)
        equation = getattr(root.relationship.constraints, name)
        variable.set_value(number)
        assert value(equation.body) == pytest.approx(0, abs=1e-09)
        variable.set_value(number + 1)
        assert abs(value(equation.body)) == pytest.approx(1)
    assert_units_consistent(model)


def test_generic_property_arguments_create_distinct_state_occurrences():
    library = Library()
    original = json.dumps(
        {k: v.model_dump(by_alias=True) for k, v in library.models.items()},
        sort_keys=True,
    )
    model = build_model(
        "water_property_pair", select(library, "water_property_pair"), library=library
    )
    pair = model.fs.root.relationship.models.states
    inlet = pair.relationship.models.inlet.structs
    outlet = pair.relationship.models.outlet.structs
    assert inlet.state.pressure is not outlet.state.pressure
    pair.structs.parameters.density.set_value(997)
    inlet.parameters.density.set_value(997)
    assert value(pair.relationship.connections.inlet_parameters.density.body) == 0
    assert (
        json.dumps(
            {k: v.model_dump(by_alias=True) for k, v in library.models.items()},
            sort_keys=True,
        )
        == original
    )


def test_model_parameter_forwarding():
    library = Library()
    library.models["forwarder"] = Model.model_validate(
        {
            "id": "forwarder",
            "structs": {},
            "model_parameters": library.get("property_pair").model_parameters,
            "relationships": {
                "forward": {
                    "models": {
                        "pair": {
                            "model": "property_pair",
                            "model_arguments": {
                                "FluidProperties": {
                                    "model_parameter": "FluidProperties"
                                }
                            },
                        }
                    },
                    "constraints": {},
                    "connections": {},
                }
            },
        }
    )
    library.models["water_property_pair"].relationships["evaluate"].models[
        "states"
    ].model = "forwarder"
    model = build_model(
        "water_property_pair", select(library, "water_property_pair"), library=library
    )
    assert (
        model.fs.root.relationship.models.states.relationship.models.pair.relationship.models.inlet.structs.properties.enthalpy
        is not None
    )


@pytest.mark.parametrize(
    "change", ["missing", "extra", "unknown_model", "unknown_parameter"]
)
def test_invalid_model_arguments_fail(change):
    library = Library()
    selection = select(library, "water_property_pair")
    ref = (
        library.models["water_property_pair"].relationships["evaluate"].models["states"]
    )
    if change == "missing":
        ref.model_arguments = {}
    elif change == "extra":
        ref.model_arguments["Extra"] = ConcreteModelReference.model_validate(
            {"model": "water_state"}
        )
    elif change == "unknown_model":
        ref.model_arguments["FluidProperties"].model = "absent"
    elif change == "unknown_parameter":
        ref.model_arguments["FluidProperties"] = ParameterModelReference.model_validate(
            {"model_parameter": "Absent"}
        )
    with pytest.raises(ValueError):
        build_model("water_property_pair", selection, library=library)


@pytest.mark.parametrize(
    "change", ["struct", "direction", "variable", "unit", "dimensions"]
)
def test_generic_argument_interface_is_checked(change):
    library = Library()
    selection = select(library, "water_property_pair")
    state = library.models["water_state"].structs
    if change == "struct":
        del state["properties"]
    elif change == "direction":
        state["properties"].direction = "input"
    elif change == "variable":
        del state["properties"].variables["enthalpy"]
    else:
        variable = state["properties"].variables["enthalpy"]
        key, val = {
            "unit": ("unit", "K"),
            "type": ("value_type", "integer"),
            "dimensions": ("dimensions", ["time"]),
        }[change]
        setattr(variable, key, val)
    with pytest.raises(ValueError, match="required|incompatible"):
        build_model("water_property_pair", selection, library=library)


def test_generic_root_is_explicitly_unsupported():
    with pytest.raises(ValueError, match="Root generic models"):
        build_model(
            "property_pair", {"model": "property_pair", "relationship": "evaluate"}
        )


def test_generic_argument_allows_extra_properties():
    library = Library()
    required = (
        library.models["property_pair"].model_parameters["FluidProperties"].requires
    )
    del required["properties"].variables["viscosity"]
    del required["properties"].variables["heat_capacity"]
    build_model(
        "water_property_pair", select(library, "water_property_pair"), library=library
    )


def test_generic_arguments_are_local_to_each_occurrence():
    from copy import deepcopy

    library = Library()
    alternative = deepcopy(library.get("water_state"))
    alternative.id = "alternative_state"
    alternative.relationships["constant_properties"].constraints[
        "density"
    ].rhs = "2 * parameters.density"
    library.models["alternative_state"] = alternative
    refs = library.models["water_property_pair"].relationships["evaluate"].models
    refs["other_states"] = deepcopy(refs["states"])
    refs["other_states"].model_arguments["FluidProperties"].model = "alternative_state"
    model = build_model(
        "water_property_pair", select(library, "water_property_pair"), library=library
    )
    pairs = model.fs.root.relationship.models
    for pair, density in [(pairs.states, 997), (pairs.other_states, 1994)]:
        child = pair.relationship.models.inlet
        child.structs.parameters.density.set_value(997)
        child.structs.properties.density.set_value(density)
        assert value(child.relationship.constraints.density.body) == pytest.approx(0)


def test_generic_child_selection_must_match_resolved_model():
    library = Library()
    selection = select(library, "water_property_pair")
    selection["submodels"]["states"]["submodels"]["inlet"]["model"] = "valve"
    with pytest.raises(ValueError, match="does not match reference"):
        build_model("water_property_pair", selection, library=library)


@pytest.mark.parametrize(
    "change", ["direction", "value_type", "determines", "reference", "name"]
)
def test_library_validates_document_shape_before_building(tmp_path, change):
    from pydantic import ValidationError

    document = Library().get("valve").model_dump(by_alias=True)
    if change == "direction":
        document["structs"]["inlet"]["direction"] = "sideways"
    elif change == "value_type":
        document["structs"]["inlet"]["variables"]["flow"]["value_type"] = "integer"
    elif change == "determines":
        del document["relationships"]["isenthalpic"]["constraints"]["eq_1"][
            "determines"
        ]
    elif change == "reference":
        document["relationships"]["isenthalpic"]["models"]["bad"] = {
            "model": "valve",
            "model_parameter": "Fluid",
        }
    else:
        document["structs"]["not.a.name"] = document["structs"].pop("inlet")
    (tmp_path / "valve.json").write_text(json.dumps(document))
    with pytest.raises(ValidationError):
        Library(tmp_path)


def test_library_exposes_typed_definitions():
    library = Library()
    assert isinstance(library.get("water_state"), Model)
    assert (
        library.models["water_state"].structs["state"].variables["pressure"].unit
        == "Pa"
    )
