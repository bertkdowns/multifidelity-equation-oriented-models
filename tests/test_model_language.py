"""Construction contracts for the declarative model language; no solver needed."""

import json
import pytest
from pyomo.environ import Constraint as PyomoConstraint, Var, value
from pyomo.core.base.units_container import UnitsError
from pyomo.util.check_units import assert_units_consistent
from multifidelity.model_language import BlockLibrary, build_model, register_standard_providers
from multifidelity.model_language.definitions import (
    BlockCatalog,
    Constraint,
    ConcreteBlockReference,
    SlotBlockReference,
)


def select(library, model, formulation=None, parameters=None):
    parameters = parameters or {}
    if model == "heat_pump" and not parameters:
        parameters = {"HotSideProperties": "water_property_package", "ColdSideProperties": "water_property_package",
                      "RefrigerantProperties": "water_property_package"}
    definition = library.get(model)
    formulation = formulation or next(iter(definition.formulations))
    children = {}
    for name, ref in definition.formulations[formulation].blocks.items():
        if isinstance(ref, SlotBlockReference):
            child_model = parameters[ref.block_slot]
            child_parameters = {}
        else:
            child_model = ref.block
            child_parameters = {
                key: arg.block
                if isinstance(arg, ConcreteBlockReference)
                else parameters[arg.block_slot]
                for key, arg in ref.block_arguments.items()
            }
        children[name] = select(
            library, child_model,
            formulation="detailed" if child_model == "milk_evaporator" else None,
            parameters=child_parameters,
        )
    selection = {"formulation": formulation, "subblocks": children}
    return selection


def heat_pump_flowsheet_selection(selection):
    return {"formulation": "flowsheet",
            "subblocks": {"heat_pump": selection}}


def build_heat_pump(selection, *, library=None):
    """Build through the concrete flowsheet and return its heat-pump block."""
    from pathlib import Path

    if isinstance(selection, Path):
        selection = json.loads(selection.read_text())
    library = library or BlockLibrary()
    if "standard.lmtd" not in library._providers:
        register_standard_providers(library)
    model = build_model("heat_pump_flowsheet", heat_pump_flowsheet_selection(selection),
                        library=library)
    return model.fs.root.formulation.blocks.heat_pump


def test_every_bundled_formulation_builds_without_solver():
    def uses_provider(resolved, selection):
        formulation = resolved.formulations[selection["formulation"]]
        return formulation.definition.external is not None or any(
            uses_provider(child, selection["subblocks"][alias])
            for alias, child in formulation.blocks.items()
        )

    library = BlockLibrary()
    for name, definition in library.blocks.items():
        if definition.block_slots:
            continue
        for formulation in definition.formulations:
            selection = select(library, name, formulation)
            # Native feeds have optional dependencies and their own tests;
            # the construction-only JSON contract below excludes their internals.
            if uses_provider(library.resolve(name), selection):
                continue
            if name == "milk_evaporator" and formulation == "aggregate":
                with pytest.raises(ValueError, match="missing output determinations"):
                    build_model(
                        name, select(library, name, formulation), library=library
                    )
                continue
            model = build_model(
                name, select(library, name, formulation), library=library
            )
            assert_units_consistent(model)
            assert all((not v.fixed for v in model.component_data_objects(Var)))
            # Reusable defaults are guesses; construction still fixes nothing.


@pytest.mark.parametrize("formulation", ["aggregate", "cycle"])
def test_heat_pump_cop_is_a_public_output(formulation):
    library = BlockLibrary()
    model = build_heat_pump(select(library, "heat_pump", formulation))
    root = model
    assert "parameters" not in library.get("heat_pump").structs
    root.structs.performance.cop[0].set_value(4)
    root.structs.performance.electrical_power[0].set_value(1000)
    root.structs.performance.heating_duty[0].set_value(4000)
    if formulation == "aggregate":
        child = root.formulation.blocks.cop_model
        child.structs.parameters.cop[0].set_value(4)
        child.structs.performance.cop[0].set_value(4)
        assert value(child.formulation.constraints.cop[0].body) == pytest.approx(0)
        root.formulation.blocks.power_model.structs.performance.electrical_power[0].set_value(1000)
        assert value(root.formulation.constraints.power[0].body) == pytest.approx(0)
        assert value(root.formulation.constraints.heating_duty_from_cop[0].body) == pytest.approx(0)
    equation = root.formulation.constraints.cop[0]
    assert value(equation.body) == pytest.approx(0)
    root.structs.performance.cop[0].set_value(3)
    assert abs(value(equation.body)) > 0


@pytest.mark.parametrize("formulation", ["aggregate", "cycle"])
def test_heat_pump_property_packages_are_independent_and_connected(formulation):
    from copy import deepcopy
    from multifidelity.model_language import required_inputs

    library = BlockLibrary()
    alternative = deepcopy(library.get("water_property_package"))
    alternative.id = "alternative_package"
    alternative.formulations["constant_properties"].constraints[
        "reference_temperature"
    ].rhs = "310 * units.K"
    library.blocks[alternative.id] = alternative
    reference = library.get("heat_pump_flowsheet").formulations["flowsheet"].blocks["heat_pump"]
    reference.block_arguments["HotSideProperties"].block = alternative.id
    selection = select(library, "heat_pump", formulation, parameters={
        "HotSideProperties": alternative.id, "ColdSideProperties": "water_property_package",
        "RefrigerantProperties": "water_property_package",
    })
    resolved = library.resolve("heat_pump_flowsheet").formulations["flowsheet"].blocks["heat_pump"]
    states = resolved.formulations[formulation].blocks
    for stream in ("source_inlet", "source_outlet", "sink_inlet", "sink_outlet"):
        state = states[stream + "_state"]
        assert state.id == "state_block"
        assert state.block_arguments["FluidProperties"].id == (
            alternative.id if stream.startswith("sink") else "water_property_package"
        )
    root = build_heat_pump(selection, library=library)
    from multifidelity.model_language.standard.initialization import seed_affine_state
    for stream in ("source_inlet", "source_outlet", "sink_inlet", "sink_outlet"):
        block = getattr(root.formulation.blocks, stream + "_state")
        boundary = getattr(root.structs, stream)
        boundary.flow[0].set_value(2)
        boundary.pressure[0].set_value(200000)
        boundary.enthalpy[0].set_value(140000)
        seed_affine_state(block, 200000, 140000, flow=2)
        for field in ("flow", "pressure", "enthalpy"):
            assert value(getattr(getattr(root.formulation.connections, stream + "_state"), field)[0].body) == pytest.approx(0)
        coefficient = block.formulation.blocks.fluid.formulation.blocks.water.structs.parameters.reference_temperature
        assert value(coefficient) == (310 if stream.startswith("sink") else 298.15)
    required = required_inputs("heat_pump_flowsheet", heat_pump_flowsheet_selection(selection), library=library)
    assert len(required) == (8 if formulation == "aggregate" else 13)
    assert not any("_state." in path for path in required)
    inlet = root.formulation.blocks.source_inlet_state.formulation.blocks.fluid.formulation.blocks.water
    outlet = root.formulation.blocks.source_outlet_state.formulation.blocks.fluid.formulation.blocks.water
    assert inlet.structs.parameters.heat_capacity is not outlet.structs.parameters.heat_capacity
    assert_units_consistent(root)


def test_parent_supplies_heat_pump_property_arguments():
    from multifidelity.model_language import required_inputs

    library = BlockLibrary()
    selection = heat_pump_flowsheet_selection(select(library, "heat_pump", "aggregate"))
    build_model("heat_pump_flowsheet", selection, library=library)
    required = required_inputs("heat_pump_flowsheet", selection, library=library)
    assert len(required) == 8
    assert not any("property_parameters" in path or "_state." in path for path in required)


@pytest.mark.parametrize("expression", [
    "units.__class__", "units.K.__class__", "units.get_units", "units.not_a_unit",
])
def test_unit_literals_reject_non_unit_attributes(expression):
    library = BlockLibrary()
    library.get("water_property_package").formulations["constant_properties"].constraints[
        "reference_temperature"
    ].rhs = expression
    with pytest.raises(ValueError, match="unknown or inaccessible"):
        build_model("water_property_package", select(library, "water_property_package"), library=library)


def test_configured_property_package_checks_coefficient_units():
    library = BlockLibrary()
    library.get("water_property_package").formulations["constant_properties"].constraints[
        "reference_temperature"
    ].rhs = "298.15 * units.Pa"
    with pytest.raises(UnitsError):
        build_model("water_property_package", select(library, "water_property_package"), library=library)


@pytest.mark.parametrize("change", ["missing", "extra", "incompatible"])
def test_heat_pump_property_arguments_are_validated_on_parent_reference(change):
    from multifidelity.model_language import required_inputs

    library = BlockLibrary()
    selection = heat_pump_flowsheet_selection(select(library, "heat_pump", "aggregate"))
    reference = library.get("heat_pump_flowsheet").formulations["flowsheet"].blocks["heat_pump"]
    arguments = reference.block_arguments
    if change == "missing":
        del arguments["HotSideProperties"]
    elif change == "extra":
        arguments["Extra"] = ConcreteBlockReference(block="water_state_ph")
    else:
        arguments["HotSideProperties"].block = "water_state"
    for method in (build_model, required_inputs):
        with pytest.raises(ValueError, match="block arguments|missing required variable"):
            method("heat_pump_flowsheet", selection, library=library)


def test_reused_definition_has_distinct_occurrences_and_connection_equations(tmp_path):
    library = BlockLibrary()
    selection = select(library, "heat_pump", "cycle")
    path = tmp_path / "model_selection.json"
    path.write_text(json.dumps(selection))
    model = build_heat_pump(path, library=library)
    parts = model.formulation.blocks
    a, b = (
        parts.condenser.structs.hot_inlet.flow[0],
        parts.subcooler.structs.hot_inlet.flow[0],
    )
    assert a is not b
    previous = b.value
    a.set_value(3)
    assert b.value == previous
    equation = model.formulation.connections.link_2.flow[0]
    parts.condenser.structs.hot_outlet.flow[0].set_value(3)
    b.set_value(2)
    assert abs(value(equation.body)) == 1


@pytest.mark.parametrize("change", ["missing", "extra", "unknown"])
def test_incomplete_or_invalid_selections_fail(change):
    library = BlockLibrary()
    selection = select(library, "heat_pump", "cycle")
    if change == "missing":
        del selection["subblocks"]["compressor"]
    elif change == "extra":
        selection["subblocks"]["unused"] = {}
    else:
        selection["subblocks"]["compressor"]["formulation"] = "nonexistent"
    with pytest.raises(ValueError):
        build_heat_pump(selection, library=library)


@pytest.mark.parametrize(
    "expression",
    ['__import__("os").getcwd()', "compressor.inlet.flow", "inlet.__class__"],
)
def test_expression_language_rejects_execution_and_out_of_scope_references(expression):
    library = BlockLibrary()
    library.blocks["valve"].formulations["isenthalpic"].constraints["bad"] = (
        Constraint.model_validate(
            {"for_each": {"t": "time"}, "lhs": 'outlet.flow[t]', "rhs": expression, "determines": 'outlet.flow[t]'}
        )
    )
    with pytest.raises(ValueError):
        build_model("valve", select(library, "valve"), library=library)


def test_unselected_formulation_is_not_loaded():
    library = BlockLibrary()
    library.blocks["heat_pump"].formulations["cycle"].blocks[
        "compressor"
    ].block = "absent"
    model = build_heat_pump(select(library, "heat_pump", "aggregate"), library=library
    )
    assert set(model.formulation.blocks.component_map()) == {
        "cop_model", "source_inlet_state", "source_outlet_state",
        "sink_inlet_state", "sink_outlet_state", "power_model",
    }


def test_only_selected_child_interface_is_accessible():
    library = BlockLibrary()
    library.blocks["heat_pump"].formulations["cycle"].constraints["bad"] = (
        Constraint.model_validate(
            {"for_each": {"t": "time"},
                "lhs": 'performance.heating_duty[t]',
                "rhs": 'compressor.hidden.inputs.work[t]',
                "determines": 'performance.heating_duty[t]',
            }
        )
    )
    # Keep a single determination so this test isolates reference visibility.
    del library.blocks["heat_pump"].formulations["cycle"].constraints["sink_heat_balance"]
    with pytest.raises(ValueError, match="inaccessible"):
        build_heat_pump(select(library, "heat_pump", "cycle"), library=library)


@pytest.mark.parametrize("change", ["fields", "direction", "units"])
def test_incompatible_connections_fail(change):
    library = BlockLibrary()
    inlet = library.blocks["valve"].structs["inlet"]
    if change == "fields":
        del inlet.variables["enthalpy"]
    elif change == "direction":
        inlet.direction = "output"
    else:
        inlet.variables["flow"].unit = "K"
    with pytest.raises(UnitsError if change == "units" else ValueError):
        build_model("source_loop", select(library, "source_loop"), library=library)


def test_library_rejects_duplicate_ids(tmp_path):
    catalog = BlockLibrary().get("valve")
    for name in ["a", "b"]:
        (tmp_path / f"{name}.json").write_text(catalog.model_dump_json(by_alias=True))
    with pytest.raises(ValueError, match="Duplicate"):
        BlockLibrary(tmp_path)


def test_missing_outputs_are_listed():
    library = BlockLibrary()
    constraints = library.blocks["valve"].formulations["isenthalpic"].constraints
    del constraints["mass_balance"]
    del constraints["enthalpy_balance"]
    with pytest.raises(
        ValueError,
        match="valve.isenthalpic: missing output determinations: outlet.enthalpy, outlet.flow",
    ):
        build_model("valve", select(library, "valve"), library=library)


def test_duplicate_constraints_name_both_sources():
    library = BlockLibrary()
    constraints = library.blocks["valve"].formulations["isenthalpic"].constraints
    constraints["another_flow"] = constraints["mass_balance"].model_copy()
    with pytest.raises(
        ValueError, match="duplicate determination.*outlet.flow.*mass_balance.*another_flow"
    ):
        build_model("valve", select(library, "valve"), library=library)


@pytest.mark.parametrize("kind", ["connection", "constraint"])
def test_connections_share_determination_namespace(kind):
    library = BlockLibrary()
    formulation = library.blocks["heat_pump"].formulations["cycle"]
    if kind == "connection":
        formulation.connections["duplicate"] = formulation.connections[
            "link_1"
        ].model_copy()
    else:
        formulation.constraints["duplicate"] = Constraint.model_validate(
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


@pytest.mark.parametrize("target", ["inlet.flow", "missing.value"])
def test_constraint_target_must_be_valid(target):
    library = BlockLibrary()
    equation = library.blocks["valve"].formulations["isenthalpic"].constraints["mass_balance"]
    equation.determines = target + "[t]"
    with pytest.raises(ValueError, match="invalid target"):
        build_model("valve", select(library, "valve"), library=library)


def test_child_output_cannot_be_determined_by_containing_formulation():
    library = BlockLibrary()
    library.blocks["heat_pump"].formulations["cycle"].constraints["bad"] = (
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
    library = BlockLibrary()
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
    library = BlockLibrary()
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
        equation = getattr(root.formulation.constraints, name)[0]
        variable.set_value(number)
        assert value(equation.body) == pytest.approx(0, abs=1e-09)
        variable.set_value(number + 1)
        assert abs(value(equation.body)) == pytest.approx(1)
    assert_units_consistent(model)


def test_generic_property_arguments_create_distinct_state_occurrences():
    from copy import deepcopy

    library = BlockLibrary()
    refs = library.get("water_state_block").formulations["evaluate"].blocks
    refs["other_states"] = deepcopy(refs["states"])
    original = json.dumps(
        {k: v.model_dump(by_alias=True) for k, v in library.blocks.items()},
        sort_keys=True,
    )
    model = build_model(
        "water_state_block", select(library, "water_state_block"), library=library
    )
    block = model.fs.root.formulation.blocks.states
    other = model.fs.root.formulation.blocks.other_states
    fluid = block.formulation.blocks.fluid
    assert block.structs.state.pressure is not other.structs.state.pressure
    assert fluid.structs.state.pressure is not other.formulation.blocks.fluid.structs.state.pressure
    assert not hasattr(block.structs, "parameters")
    block.structs.state.enthalpy[0].set_value(140000)
    fluid.structs.state.enthalpy[0].set_value(140000)
    assert value(block.formulation.constraints.enthalpy[0].body) == 0
    block.structs.properties.temperature[0].set_value(310)
    fluid.structs.properties.temperature[0].set_value(310)
    assert value(block.formulation.constraints.temperature[0].body) == 0
    a = fluid.formulation.blocks.water.structs.parameters.density
    b = other.formulation.blocks.fluid.formulation.blocks.water.structs.parameters.density
    assert a is not b
    assert json.dumps(
        {k: v.model_dump(by_alias=True) for k, v in library.blocks.items()},
        sort_keys=True,
    ) == original


def test_block_slot_forwarding():
    library = BlockLibrary()
    library.blocks["forwarder"] = BlockCatalog.model_validate(
        {
            "id": "forwarder",
            "domains": {"time": {"kind": "time"}},
            "structs": {},
            "block_slots": library.get("state_block").block_slots,
            "formulations": {
                "forward": {
                    "blocks": {
                        "pair": {
                            "block": "state_block",
                            "domain_bindings": {"time": "time"},
                            "block_arguments": {
                                "FluidProperties": {
                                    "block_slot": "FluidProperties"
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
    library.blocks["water_state_block"].formulations["evaluate"].blocks[
        "states"
    ].block = "forwarder"
    model = build_model(
        "water_state_block", select(library, "water_state_block"), library=library
    )
    assert (
        model.fs.root.formulation.blocks.states.formulation.blocks.pair.formulation.blocks.fluid.structs.properties.temperature[0]
        is not None
    )


@pytest.mark.parametrize(
    "change", ["missing", "extra", "unknown_model", "unknown_parameter"]
)
def test_invalid_block_arguments_fail(change):
    library = BlockLibrary()
    selection = select(library, "water_state_block")
    ref = (
        library.blocks["water_state_block"].formulations["evaluate"].blocks["states"]
    )
    if change == "missing":
        ref.block_arguments = {}
    elif change == "extra":
        ref.block_arguments["Extra"] = ConcreteBlockReference.model_validate(
            {"block": "water_state"}
        )
    elif change == "unknown_model":
        ref.block_arguments["FluidProperties"].block = "absent"
    elif change == "unknown_parameter":
        ref.block_arguments["FluidProperties"] = SlotBlockReference.model_validate(
            {"block_slot": "Absent"}
        )
    with pytest.raises(ValueError):
        build_model("water_state_block", selection, library=library)


@pytest.mark.parametrize(
    "change", ["struct", "direction", "variable", "unit", "dimensions"]
)
def test_generic_argument_interface_is_checked(change):
    library = BlockLibrary()
    selection = select(library, "water_state_block")
    state = library.blocks["water_property_package"].structs
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
    with pytest.raises(ValueError, match="Root generic blocks"):
        build_model(
            "state_block", {"formulation": "evaluate"}
        )


def test_generic_argument_allows_extra_properties():
    library = BlockLibrary()
    required = (
        library.blocks["state_block"].block_slots["FluidProperties"].requires
    )
    del required["properties"].variables["entropy"]
    del required["properties"].variables["heat_capacity"]
    build_model(
        "water_state_block", select(library, "water_state_block"), library=library
    )


def test_generic_arguments_are_local_to_each_occurrence():
    from copy import deepcopy

    library = BlockLibrary()
    alternative = deepcopy(library.get("water_property_package"))
    alternative.id = "alternative_state"
    alternative.formulations["constant_properties"].constraints[
        "density"
    ].rhs = "1994 * units.kg / units.m**3"
    library.blocks["alternative_state"] = alternative
    refs = library.blocks["water_state_block"].formulations["evaluate"].blocks
    refs["other_states"] = deepcopy(refs["states"])
    refs["other_states"].block_arguments["FluidProperties"].block = "alternative_state"
    model = build_model(
        "water_state_block", select(library, "water_state_block"), library=library
    )
    pairs = model.fs.root.formulation.blocks
    for pair, density in [(pairs.states, 997), (pairs.other_states, 1994)]:
        child = pair.formulation.blocks.fluid
        water = child.formulation.blocks.water
        water.structs.parameters.density.set_value(density)
        equation = child.formulation.constraints.density
        assert value(equation.body) == pytest.approx(value(equation.lower))


def test_child_selection_cannot_override_model_reference():
    library = BlockLibrary()
    selection = select(library, "water_state_block")
    selection["subblocks"]["states"]["subblocks"]["fluid"]["block"] = "valve"
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        build_model("water_state_block", selection, library=library)


@pytest.mark.parametrize(
    "change", ["direction", "value_type", "determines", "reference", "name"]
)
def test_library_validates_catalog_shape_before_building(tmp_path, change):
    from pydantic import ValidationError

    catalog = BlockLibrary().get("valve").model_dump(by_alias=True)
    if change == "direction":
        catalog["structs"]["inlet"]["direction"] = "sideways"
    elif change == "value_type":
        catalog["structs"]["inlet"]["variables"]["flow"]["value_type"] = "integer"
    elif change == "determines":
        del catalog["formulations"]["isenthalpic"]["constraints"]["mass_balance"][
            "determines"
        ]
    elif change == "reference":
        catalog["formulations"]["isenthalpic"]["blocks"]["bad"] = {
            "block": "valve",
            "block_slot": "Fluid",
        }
    else:
        catalog["structs"]["not.a.name"] = catalog["structs"].pop("inlet")
    (tmp_path / "valve.json").write_text(json.dumps(catalog))
    with pytest.raises(ValidationError):
        BlockLibrary(tmp_path)


def test_library_exposes_typed_definitions():
    library = BlockLibrary()
    assert isinstance(library.get("water_state"), BlockCatalog)
    assert (
        library.blocks["water_state"].structs["state"].variables["pressure"].unit
        == "Pa"
    )


def test_heat_pump_evaporator_example_connects_steam_and_serial_effects():
    from pathlib import Path
    from pyomo.core.expr.visitor import identify_variables

    model_catalog = Path("examples/model_language/heat_pump_evaporator_flowsheet.json")
    library = BlockLibrary()
    register_standard_providers(library)
    model = build_model("heat_pump_evaporator_flowsheet", model_catalog, library=library)
    assert_units_consistent(model)
    root = model.fs.root
    children = root.formulation.blocks
    connections = root.formulation.connections
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
    assert not {"water_state_ps", "water_isentropic_package", "steam_generating_heat_pump", "water_flash"} & BlockLibrary().blocks.keys()


def test_evaporator_flowsheet_accepts_aggregate_steam_heat_pump():
    from pathlib import Path

    model_catalog = json.loads(Path("examples/model_language/heat_pump_evaporator_flowsheet.json").read_text())
    model_catalog["subblocks"]["heat_pump"]["subblocks"]["sghp"] = select(BlockLibrary(), "steam_generating_heat_pump_unit", "aggregate")
    library = BlockLibrary()
    register_standard_providers(library)
    model = build_model("heat_pump_evaporator_flowsheet", model_catalog, library=library)
    assert_units_consistent(model)
