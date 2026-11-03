"""Required specifications are derived before any instance values are supplied."""

from pathlib import Path

import pytest

from multifidelity.model_language import Library, required_inputs, print_required_inputs
from multifidelity.model_language.definitions import Constraint, Connection
from multifidelity.model_language.implementation import ImplementationDocument


EXAMPLES = Path(__file__).parents[1] / "examples/model_language"


def test_leaf_requires_all_inputs_and_no_outputs(capsys):
    selection = ImplementationDocument(relationship="isenthalpic")
    required = required_inputs("valve", selection)
    assert set(required) == {
        "inlet.flow",
        "inlet.pressure",
        "inlet.enthalpy",
        "parameters.pressure_drop",
    }
    assert required["inlet.flow"].unit == "kg/s"
    print_required_inputs("valve", selection)
    assert capsys.readouterr().out.splitlines() == [
        "inlet.enthalpy [J/kg]",
        "inlet.flow [kg/s]",
        "inlet.pressure [Pa]",
        "parameters.pressure_drop [Pa]",
    ]


def test_recursive_connections_do_not_duplicate_parameter_requirements(monkeypatch):
    from multifidelity.model_language import builder

    def forbidden():
        raise AssertionError("Input discovery must not construct Pyomo")

    monkeypatch.setattr(builder, "ConcreteModel", forbidden)
    library = Library()
    before = {name: model.model_dump() for name, model in library.models.items()}
    required = required_inputs(
        "water_state_block",
        EXAMPLES / "water_state_block_evaluate.json",
        library=library,
    )
    assert set(required) == {
        "states.state.flow",
        "states.state.pressure",
        "states.state.enthalpy",
    }
    assert {
        name: model.model_dump() for name, model in library.models.items()
    } == before


def test_constraints_supply_individual_child_inputs():
    required = required_inputs("heat_pump_flowsheet", EXAMPLES / "heat_pump_cycle.json")
    assert len(required) == 13
    assert "heat_pump.parameters.cop" not in required
    assert "heat_pump.performance.cop" not in required
    assert "heat_pump.performance.electrical_power" not in required
    assert "heat_pump.compressor.parameters.efficiency" in required
    assert "heat_pump.compressor.parameters.work" not in required
    assert "heat_pump.compressor.parameters.pressure_rise" in required
    assert "heat_pump.condenser.parameters.conductance" in required
    assert "heat_pump.subcooler.parameters.conductance" in required
    assert "heat_pump.condenser.hot_inlet.flow" not in required


def test_configured_water_package_only_requires_state():
    required = required_inputs(
        "water_property_package", EXAMPLES / "water_property_package_constant_properties.json"
    )
    assert set(required) == {"state.pressure", "state.enthalpy"}


def test_partial_child_struct_still_lists_other_inputs():
    library = Library()
    rel = library.get("water_state_block").relationships["evaluate"]
    rel.constraints["pressure"] = Constraint(for_each={"t": "time"},
        lhs='states.state.pressure[t]',
        rhs='100000 * units.Pa',
        determines='states.state.pressure[t]',
    )
    required = required_inputs(
        "water_state_block",
        EXAMPLES / "water_state_block_evaluate.json",
        library=library,
    )
    assert "states.state.pressure" not in required
    assert "states.state.enthalpy" in required
    assert "states.state.flow" in required


def test_only_selected_relationships_are_traversed():
    library = Library()
    library.get("heat_pump").relationships["cycle"].models[
        "compressor"
    ].model = "absent"
    required = required_inputs(
        "heat_pump_flowsheet", EXAMPLES / "heat_pump_aggregate.json", library=library
    )
    assert len(required) == 8
    assert "heat_pump.cop_model.parameters.cop" in required
    assert "heat_pump.parameters.cop" not in required


@pytest.mark.parametrize(
    "change",
    [
        "missing_child",
        "extra_child",
        "unknown_relationship",
    ],
)
def test_invalid_implementations_do_not_produce_incomplete_lists(change):
    selection = ImplementationDocument.model_validate_json(
        (EXAMPLES / "water_state_block_evaluate.json").read_text()
    )
    if change == "missing_child":
        del selection.submodels["states"]
    elif change == "extra_child":
        selection.submodels["other"] = selection.submodels["states"]
    elif change == "unknown_relationship":
        selection.relationship = "absent"
    with pytest.raises(ValueError):
        required_inputs("water_state_block", selection)


@pytest.mark.parametrize("kind", ["constraint", "connection"])
def test_duplicate_determinations_are_rejected(kind):
    library = Library()
    rel = library.get("state_block").relationships["evaluate"]
    if kind == "connection":
        # Match the concrete package fields to isolate duplicate-target validation.
        library.get("state_block").structs["properties"].variables["viscosity"] = library.get("water_property_package").structs["properties"].variables["viscosity"]
        rel.connections["duplicate"] = Connection(from_="fluid.properties", to="properties")
    else:
        rel.constraints["duplicate"] = Constraint(for_each={"t": "time"},
            lhs='fluid.state.pressure[t]',
            rhs='state.pressure[t]',
            determines='fluid.state.pressure[t]',
        )
    with pytest.raises(ValueError, match="duplicate determination"):
        required_inputs(
            "water_state_block",
            EXAMPLES / "water_state_block_evaluate.json",
            library=library,
        )


def test_missing_output_definitions_are_rejected():
    with pytest.raises(ValueError, match="missing output determinations"):
        required_inputs("milk_evaporator", EXAMPLES / "milk_evaporator_aggregate.json")


def test_dictionary_input_and_file_output():
    from io import StringIO

    output = StringIO()
    print_required_inputs(
        "valve", {"relationship": "isenthalpic"}, file=output
    )
    assert "parameters.pressure_drop [Pa]" in output.getvalue()
