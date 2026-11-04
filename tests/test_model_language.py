"""Construction contracts for the declarative model language; no solver needed."""

import json
import pytest
from pyomo.environ import Constraint as PyomoConstraint, Var, value
from pyomo.core.base.units_container import UnitsError
from pyomo.util.check_units import assert_units_consistent
from multifidelity.model_language import Library, build_model, register_standard_providers
from multifidelity.model_language.definitions import (
    ModelDocument,
    Constraint,
    ConcreteModelReference,
    ParameterModelReference,
)


def select(library, model, relationship=None, parameters=None):
    parameters = parameters or {}
    if model == "heat_pump" and not parameters:
        parameters = {"HotSideProperties": "water_property_package", "ColdSideProperties": "water_property_package",
                      "RefrigerantProperties": "water_property_package"}
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
        children[name] = select(
            library, child_model,
            relationship="detailed" if child_model == "milk_evaporator" else None,
            parameters=child_parameters,
        )
    selection = {"relationship": relationship, "submodels": children}
    return selection


def heat_pump_flowsheet_selection(selection):
    return {"relationship": "flowsheet",
            "submodels": {"heat_pump": selection}}


def build_heat_pump(selection, *, library=None):
    """Build through the concrete flowsheet and return its heat-pump block."""
    from pathlib import Path

    if isinstance(selection, Path):
        selection = json.loads(selection.read_text())
    library = library or Library()
    if "standard.lmtd" not in library._providers:
        register_standard_providers(library)
    model = build_model("heat_pump_flowsheet", heat_pump_flowsheet_selection(selection),
                        library=library)
    return model.fs.root.relationship.models.heat_pump


def test_every_bundled_relationship_builds_without_solver():
    def uses_provider(resolved, selection):
        relationship = resolved.relationships[selection["relationship"]]
        return relationship.definition.external is not None or any(
            uses_provider(child, selection["submodels"][alias])
            for alias, child in relationship.models.items()
        )

    library = Library()
    for name, definition in library.models.items():
        if definition.model_parameters:
            continue
        for relationship in definition.relationships:
            selection = select(library, name, relationship)
            # Native providers have optional dependencies and their own tests;
            # the construction-only JSON contract below excludes their internals.
            if uses_provider(library.resolve(name), selection):
                continue
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
            # Reusable defaults are guesses; construction still fixes nothing.


@pytest.mark.parametrize("relationship", ["aggregate", "cycle"])
def test_heat_pump_cop_is_a_public_output(relationship):
    library = Library()
    model = build_heat_pump(select(library, "heat_pump", relationship))
    root = model
    assert "parameters" not in library.get("heat_pump").structs
    root.structs.performance.cop[0].set_value(4)
    root.structs.performance.electrical_power[0].set_value(1000)
    root.structs.performance.heating_duty[0].set_value(4000)
    if relationship == "aggregate":
        child = root.relationship.models.cop_model
        child.structs.parameters.cop[0].set_value(4)
        child.structs.performance.cop[0].set_value(4)
        assert value(child.relationship.constraints.cop[0].body) == pytest.approx(0)
        root.relationship.models.power_model.structs.performance.electrical_power[0].set_value(1000)
        assert value(root.relationship.constraints.power[0].body) == pytest.approx(0)
        assert value(root.relationship.constraints.heating_duty_from_cop[0].body) == pytest.approx(0)
    equation = root.relationship.constraints.cop[0]
    assert value(equation.body) == pytest.approx(0)
    root.structs.performance.cop[0].set_value(3)
    assert abs(value(equation.body)) > 0


@pytest.mark.parametrize("relationship", ["aggregate", "cycle"])
def test_heat_pump_property_packages_are_independent_and_connected(relationship):
    from copy import deepcopy
    from multifidelity.model_language import required_inputs

    library = Library()
    alternative = deepcopy(library.get("water_property_package"))
    alternative.id = "alternative_package"
    alternative.relationships["constant_properties"].constraints[
        "reference_temperature"
    ].rhs = "310 * units.K"
    library.models[alternative.id] = alternative
    reference = library.get("heat_pump_flowsheet").relationships["flowsheet"].models["heat_pump"]
    reference.model_arguments["HotSideProperties"].model = alternative.id
    selection = select(library, "heat_pump", relationship, parameters={
        "HotSideProperties": alternative.id, "ColdSideProperties": "water_property_package",
        "RefrigerantProperties": "water_property_package",
    })
    resolved = library.resolve("heat_pump_flowsheet").relationships["flowsheet"].models["heat_pump"]
    states = resolved.relationships[relationship].models
    for stream in ("source_inlet", "source_outlet", "sink_inlet", "sink_outlet"):
        state = states[stream + "_state"]
        assert state.id == "state_block"
        assert state.model_arguments["FluidProperties"].id == (
            alternative.id if stream.startswith("sink") else "water_property_package"
        )
    root = build_heat_pump(selection, library=library)
    from multifidelity.model_language.standard.initialization import seed_affine_state
    for stream in ("source_inlet", "source_outlet", "sink_inlet", "sink_outlet"):
        block = getattr(root.relationship.models, stream + "_state")
        boundary = getattr(root.structs, stream)
        boundary.flow[0].set_value(2)
        boundary.pressure[0].set_value(200000)
        boundary.enthalpy[0].set_value(140000)
        seed_affine_state(block, 200000, 140000, flow=2)
        for field in ("flow", "pressure", "enthalpy"):
            assert value(getattr(getattr(root.relationship.connections, stream + "_state"), field)[0].body) == pytest.approx(0)
        coefficient = block.relationship.models.fluid.relationship.models.water.structs.parameters.reference_temperature
        assert value(coefficient) == (310 if stream.startswith("sink") else 298.15)
    required = required_inputs("heat_pump_flowsheet", heat_pump_flowsheet_selection(selection), library=library)
    assert len(required) == (8 if relationship == "aggregate" else 13)
    assert not any("_state." in path for path in required)
    inlet = root.relationship.models.source_inlet_state.relationship.models.fluid.relationship.models.water
    outlet = root.relationship.models.source_outlet_state.relationship.models.fluid.relationship.models.water
    assert inlet.structs.parameters.heat_capacity is not outlet.structs.parameters.heat_capacity
    assert_units_consistent(root)


def test_parent_supplies_heat_pump_property_arguments():
    from multifidelity.model_language import required_inputs

    library = Library()
    selection = heat_pump_flowsheet_selection(select(library, "heat_pump", "aggregate"))
    build_model("heat_pump_flowsheet", selection, library=library)
    required = required_inputs("heat_pump_flowsheet", selection, library=library)
    assert len(required) == 8
    assert not any("property_parameters" in path or "_state." in path for path in required)


@pytest.mark.parametrize("expression", [
    "units.__class__", "units.K.__class__", "units.get_units", "units.not_a_unit",
])
def test_unit_literals_reject_non_unit_attributes(expression):
    library = Library()
    library.get("water_property_package").relationships["constant_properties"].constraints[
        "reference_temperature"
    ].rhs = expression
    with pytest.raises(ValueError, match="unknown or inaccessible"):
        build_model("water_property_package", select(library, "water_property_package"), library=library)


def test_configured_property_package_checks_coefficient_units():
    library = Library()
    library.get("water_property_package").relationships["constant_properties"].constraints[
        "reference_temperature"
    ].rhs = "298.15 * units.Pa"
    with pytest.raises(UnitsError):
        build_model("water_property_package", select(library, "water_property_package"), library=library)


@pytest.mark.parametrize("change", ["missing", "extra", "incompatible"])
def test_heat_pump_property_arguments_are_validated_on_parent_reference(change):
    from multifidelity.model_language import required_inputs

    library = Library()
    selection = heat_pump_flowsheet_selection(select(library, "heat_pump", "aggregate"))
    reference = library.get("heat_pump_flowsheet").relationships["flowsheet"].models["heat_pump"]
    arguments = reference.model_arguments
    if change == "missing":
        del arguments["HotSideProperties"]
    elif change == "extra":
        arguments["Extra"] = ConcreteModelReference(model="water_state_ph")
    else:
        arguments["HotSideProperties"].model = "water_state"
    for method in (build_model, required_inputs):
        with pytest.raises(ValueError, match="model arguments|missing required variable"):
            method("heat_pump_flowsheet", selection, library=library)


def test_reused_definition_has_distinct_occurrences_and_connection_equations(tmp_path):
    library = Library()
    selection = select(library, "heat_pump", "cycle")
    path = tmp_path / "implementation.json"
    path.write_text(json.dumps(selection))
    model = build_heat_pump(path, library=library)
    parts = model.relationship.models
    a, b = (
        parts.condenser.structs.hot_inlet.flow[0],
        parts.subcooler.structs.hot_inlet.flow[0],
    )
    assert a is not b
    a.set_value(3)
    assert b.value is None
    equation = model.relationship.connections.link_2.flow[0]
    parts.condenser.structs.hot_outlet.flow[0].set_value(3)
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
        build_heat_pump(selection, library=library)


@pytest.mark.parametrize(
    "expression",
    ['__import__("os").getcwd()', "compressor.inlet.flow", "inlet.__class__"],
)
def test_expression_language_rejects_execution_and_out_of_scope_references(expression):
    library = Library()
    library.models["valve"].relationships["isenthalpic"].constraints["bad"] = (
        Constraint.model_validate(
            {"for_each": {"t": "time"}, "lhs": 'outlet.flow[t]', "rhs": expression, "determines": 'outlet.flow[t]'}
        )
    )
    with pytest.raises(ValueError):
        build_model("valve", select(library, "valve"), library=library)


def test_unselected_relationship_is_not_loaded():
    library = Library()
    library.models["heat_pump"].relationships["cycle"].models[
        "compressor"
    ].model = "absent"
    model = build_heat_pump(select(library, "heat_pump", "aggregate"), library=library
    )
    assert set(model.relationship.models.component_map()) == {
        "cop_model", "source_inlet_state", "source_outlet_state",
        "sink_inlet_state", "sink_outlet_state", "power_model",
    }


def test_only_selected_child_interface_is_accessible():
    library = Library()
    library.models["heat_pump"].relationships["cycle"].constraints["bad"] = (
        Constraint.model_validate(
            {"for_each": {"t": "time"},
                "lhs": 'performance.heating_duty[t]',
                "rhs": 'compressor.hidden.inputs.work[t]',
                "determines": 'performance.heating_duty[t]',
            }
        )
    )
    # Keep a single determination so this test isolates reference visibility.
    del library.models["heat_pump"].relationships["cycle"].constraints["sink_heat_balance"]
    with pytest.raises(ValueError, match="inaccessible"):
        build_heat_pump(select(library, "heat_pump", "cycle"), library=library)


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
    del constraints["mass_balance"]
    del constraints["enthalpy_balance"]
    with pytest.raises(
        ValueError,
        match="valve.isenthalpic: missing output determinations: outlet.enthalpy, outlet.flow",
    ):
        build_model("valve", select(library, "valve"), library=library)


def test_duplicate_constraints_name_both_sources():
    library = Library()
    constraints = library.models["valve"].relationships["isenthalpic"].constraints
    constraints["another_flow"] = constraints["mass_balance"].model_copy()
    with pytest.raises(
        ValueError, match="duplicate determination.*outlet.flow.*mass_balance.*another_flow"
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
            {"for_each": {"t": "time"},
                "lhs": 'condenser.hot_inlet.flow[t]',
                "rhs": 'compressor.outlet.flow[t]',
                "determines": 'condenser.hot_inlet.flow[t]',
            }
        )
    with pytest.raises(
        ValueError, match="duplicate determination.*condenser.hot_inlet.flow"
    ):
        build_heat_pump(select(library, "heat_pump", "cycle"), library=library)


@pytest.mark.parametrize("target", ["inlet.flow", "missing.value", "outlet.pressure"])
def test_constraint_target_must_be_valid_and_occur_in_equation(target):
    library = Library()
    equation = library.models["valve"].relationships["isenthalpic"].constraints["mass_balance"]
    equation.determines = target + "[t]"
    if target == "outlet.pressure":
        # Swap targets to retain complete coverage without duplicate targets.
        library.models["valve"].relationships["isenthalpic"].constraints[
            "pressure_balance"
        ].determines = "outlet.flow[t]"
    with pytest.raises(ValueError, match="invalid target|does not occur"):
        build_model("valve", select(library, "valve"), library=library)


def test_child_output_cannot_be_determined_by_containing_relationship():
    library = Library()
    library.models["heat_pump"].relationships["cycle"].constraints["bad"] = (
        Constraint.model_validate(
            {"for_each": {"t": "time"},
                "lhs": 'compressor.outlet.flow[t]',
                "rhs": 'compressor.inlet.flow[t]',
                "determines": 'compressor.outlet.flow[t]',
            }
        )
    )
    with pytest.raises(ValueError, match="invalid target"):
        build_heat_pump(select(library, "heat_pump", "cycle"), library=library)


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
    root.structs.state.temperature[0].set_value(temperature)
    root.structs.state.pressure[0].set_value(pressure)
    coefficients = {
        "reference_temperature": 298.15,
        "reference_pressure": 101325,
        "reference_enthalpy": 104920.1198085,
        "heat_capacity": 4180,
        "density": 997,
        "viscosity": 0.00089,
        "reference_entropy": 367.1996421,
        "thermal_expansion": 0.000257,
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
        "entropy": 367.1996421 + 4180 / 298.15 * (temperature - 298.15)
        - 0.000257 / 997 * (pressure - 101325),
    }
    for name, number in expected.items():
        variable = getattr(root.structs.properties, name)[0]
        equation = getattr(root.relationship.constraints, name)[0]
        variable.set_value(number)
        assert value(equation.body) == pytest.approx(0, abs=1e-09)
        variable.set_value(number + 1)
        assert abs(value(equation.body)) == pytest.approx(1)
    assert_units_consistent(model)


def test_generic_property_arguments_create_distinct_state_occurrences():
    from copy import deepcopy

    library = Library()
    refs = library.get("water_state_block").relationships["evaluate"].models
    refs["other_states"] = deepcopy(refs["states"])
    original = json.dumps(
        {k: v.model_dump(by_alias=True) for k, v in library.models.items()},
        sort_keys=True,
    )
    model = build_model(
        "water_state_block", select(library, "water_state_block"), library=library
    )
    block = model.fs.root.relationship.models.states
    other = model.fs.root.relationship.models.other_states
    fluid = block.relationship.models.fluid
    assert block.structs.state.pressure is not other.structs.state.pressure
    assert fluid.structs.state.pressure is not other.relationship.models.fluid.structs.state.pressure
    assert not hasattr(block.structs, "parameters")
    block.structs.state.enthalpy[0].set_value(140000)
    fluid.structs.state.enthalpy[0].set_value(140000)
    assert value(block.relationship.constraints.enthalpy[0].body) == 0
    block.structs.properties.temperature[0].set_value(310)
    fluid.structs.properties.temperature[0].set_value(310)
    assert value(block.relationship.constraints.temperature[0].body) == 0
    a = fluid.relationship.models.water.structs.parameters.density
    b = other.relationship.models.fluid.relationship.models.water.structs.parameters.density
    assert a is not b
    assert json.dumps(
        {k: v.model_dump(by_alias=True) for k, v in library.models.items()},
        sort_keys=True,
    ) == original


def test_model_parameter_forwarding():
    library = Library()
    library.models["forwarder"] = ModelDocument.model_validate(
        {
            "id": "forwarder",
            "domains": {"time": {"kind": "time"}},
            "structs": {},
            "model_parameters": library.get("state_block").model_parameters,
            "relationships": {
                "forward": {
                    "models": {
                        "pair": {
                            "model": "state_block",
                            "domain_bindings": {"time": "time"},
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
    library.models["water_state_block"].relationships["evaluate"].models[
        "states"
    ].model = "forwarder"
    model = build_model(
        "water_state_block", select(library, "water_state_block"), library=library
    )
    assert (
        model.fs.root.relationship.models.states.relationship.models.pair.relationship.models.fluid.structs.properties.temperature[0]
        is not None
    )


@pytest.mark.parametrize(
    "change", ["missing", "extra", "unknown_model", "unknown_parameter"]
)
def test_invalid_model_arguments_fail(change):
    library = Library()
    selection = select(library, "water_state_block")
    ref = (
        library.models["water_state_block"].relationships["evaluate"].models["states"]
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
        build_model("water_state_block", selection, library=library)


@pytest.mark.parametrize(
    "change", ["struct", "direction", "variable", "unit", "dimensions"]
)
def test_generic_argument_interface_is_checked(change):
    library = Library()
    selection = select(library, "water_state_block")
    state = library.models["water_property_package"].structs
    if change == "struct":
        del state["properties"]
    elif change == "direction":
        state["properties"].direction = "input"
    elif change == "variable":
        del state["properties"].variables["temperature"]
    else:
        variable = state["properties"].variables["temperature"]
        key, val = {
            "unit": ("unit", "Pa"),
            "type": ("value_type", "integer"),
            "dimensions": ("dimensions", []),
        }[change]
        setattr(variable, key, val)
    with pytest.raises(ValueError, match="required|incompatible"):
        build_model("water_state_block", selection, library=library)


def test_generic_root_is_explicitly_unsupported():
    with pytest.raises(ValueError, match="Root generic models"):
        build_model(
            "state_block", {"relationship": "evaluate"}
        )


def test_generic_argument_allows_extra_properties():
    library = Library()
    required = (
        library.models["state_block"].model_parameters["FluidProperties"].requires
    )
    del required["properties"].variables["entropy"]
    del required["properties"].variables["heat_capacity"]
    build_model(
        "water_state_block", select(library, "water_state_block"), library=library
    )


def test_generic_arguments_are_local_to_each_occurrence():
    from copy import deepcopy

    library = Library()
    alternative = deepcopy(library.get("water_property_package"))
    alternative.id = "alternative_state"
    alternative.relationships["constant_properties"].constraints[
        "density"
    ].rhs = "1994 * units.kg / units.m**3"
    library.models["alternative_state"] = alternative
    refs = library.models["water_state_block"].relationships["evaluate"].models
    refs["other_states"] = deepcopy(refs["states"])
    refs["other_states"].model_arguments["FluidProperties"].model = "alternative_state"
    model = build_model(
        "water_state_block", select(library, "water_state_block"), library=library
    )
    pairs = model.fs.root.relationship.models
    for pair, density in [(pairs.states, 997), (pairs.other_states, 1994)]:
        child = pair.relationship.models.fluid
        water = child.relationship.models.water
        water.structs.parameters.density.set_value(density)
        equation = child.relationship.constraints.density
        assert value(equation.body) == pytest.approx(value(equation.lower))


def test_child_selection_cannot_override_model_reference():
    library = Library()
    selection = select(library, "water_state_block")
    selection["submodels"]["states"]["submodels"]["fluid"]["model"] = "valve"
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        build_model("water_state_block", selection, library=library)


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
        del document["relationships"]["isenthalpic"]["constraints"]["mass_balance"][
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
    assert isinstance(library.get("water_state"), ModelDocument)
    assert (
        library.models["water_state"].structs["state"].variables["pressure"].unit
        == "Pa"
    )


def test_heat_pump_evaporator_example_connects_steam_and_serial_effects():
    from pathlib import Path
    from pyomo.core.expr.visitor import identify_variables

    implementation = Path("examples/model_language/heat_pump_evaporator_flowsheet.json")
    library = Library()
    register_standard_providers(library)
    model = build_model("heat_pump_evaporator_flowsheet", implementation, library=library)
    assert_units_consistent(model)
    root = model.fs.root
    children = root.relationship.models
    connections = root.relationship.connections
    # Connections retain separate boundary variables and couple the intended units.
    for name, source, destination in [
        ("steam_supply", children.heat_pump.structs.steam_outlet,
         children.steam_injection.structs.makeup),
        ("milk_transfer_1", children.effect_1.structs.milk_outlet,
         children.effect_2.structs.milk_inlet),
        ("milk_transfer_2", children.effect_2.structs.milk_outlet,
         children.effect_3.structs.milk_inlet),
    ]:
        block = getattr(connections, name)
        variables = {id(v) for c in block.component_data_objects(
            PyomoConstraint
        ) for v in identify_variables(c.body)}
        for field in ("flow", "pressure", "enthalpy"):
            assert id(getattr(source, field)[0]) in variables
            assert id(getattr(destination, field)[0]) in variables


def test_superseded_property_and_sghp_models_are_removed():
    assert not {"water_state_ps", "water_isentropic_package", "steam_generating_heat_pump", "water_flash"} & Library().models.keys()


def test_evaporator_flowsheet_accepts_aggregate_steam_heat_pump():
    from pathlib import Path

    implementation = json.loads(Path("examples/model_language/heat_pump_evaporator_flowsheet.json").read_text())
    implementation["submodels"]["heat_pump"]["submodels"]["sghp"] = select(Library(), "steam_generating_heat_pump_unit", "aggregate")
    library = Library()
    register_standard_providers(library)
    model = build_model("heat_pump_evaporator_flowsheet", implementation, library=library)
    assert_units_consistent(model)
