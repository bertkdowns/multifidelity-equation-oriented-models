"""Required specifications are derived before any instance values are supplied."""

from pathlib import Path

import pytest

from multifidelity.model_language import Library, required_inputs, print_required_inputs
from multifidelity.model_language.definitions import Constraint, Connection
from multifidelity.model_language.implementation import Implementation


EXAMPLES = Path(__file__).parents[1] / "examples/model_language"


def test_leaf_requires_all_inputs_and_no_outputs(capsys):
    selection = Implementation(model="valve", relationship="isenthalpic")
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
        "water_property_pair",
        EXAMPLES / "water_property_pair_evaluate.json",
        library=library,
    )
    assert set(required) == {
        "states.inlet_state.pressure",
        "states.inlet_state.enthalpy",
        "states.outlet_state.pressure",
        "states.outlet_state.enthalpy",
    }
    assert {
        name: model.model_dump() for name, model in library.models.items()
    } == before


def test_constraints_supply_individual_child_inputs():
    required = required_inputs("heat_pump_flowsheet", EXAMPLES / "heat_pump_cycle.json")
    assert len(required) == 17
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
    rel = library.get("water_property_pair").relationships["evaluate"]
    rel.constraints["pressure"] = Constraint(
        lhs="states.inlet_state.pressure",
        rhs="states.outlet_state.pressure",
        determines="states.inlet_state.pressure",
    )
    required = required_inputs(
        "water_property_pair",
        EXAMPLES / "water_property_pair_evaluate.json",
        library=library,
    )
    assert "states.inlet_state.pressure" not in required
    assert "states.inlet_state.enthalpy" in required
    assert "states.outlet_state.pressure" in required


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
        "wrong_child_model",
        "wrong_root",
    ],
)
def test_invalid_implementations_do_not_produce_incomplete_lists(change):
    selection = Implementation.model_validate_json(
        (EXAMPLES / "water_property_pair_evaluate.json").read_text()
    )
    if change == "missing_child":
        del selection.submodels["states"]
    elif change == "extra_child":
        selection.submodels["other"] = selection.submodels["states"]
    elif change == "unknown_relationship":
        selection.relationship = "absent"
    elif change == "wrong_child_model":
        selection.submodels["states"].model = "valve"
    else:
        selection.model = "valve"
    with pytest.raises(ValueError):
        required_inputs("water_property_pair", selection)


@pytest.mark.parametrize("kind", ["constraint", "connection"])
def test_duplicate_determinations_are_rejected(kind):
    library = Library()
    rel = library.get("property_pair").relationships["evaluate"]
    if kind == "connection":
        rel.connections["duplicate"] = Connection(from_="inlet_state", to="inlet.state")
    else:
        rel.constraints["duplicate"] = Constraint(
            lhs="inlet.state.pressure",
            rhs="inlet_state.pressure",
            determines="inlet.state.pressure",
        )
    with pytest.raises(ValueError, match="duplicate determination"):
        required_inputs(
            "water_property_pair",
            EXAMPLES / "water_property_pair_evaluate.json",
            library=library,
        )


def test_missing_output_definitions_are_rejected():
    with pytest.raises(ValueError, match="missing output determinations"):
        required_inputs("milk_evaporator", EXAMPLES / "milk_evaporator_aggregate.json")


def test_dictionary_input_and_file_output():
    from io import StringIO

    output = StringIO()
    print_required_inputs(
        "valve", {"model": "valve", "relationship": "isenthalpic"}, file=output
    )
    assert "parameters.pressure_drop [Pa]" in output.getvalue()
