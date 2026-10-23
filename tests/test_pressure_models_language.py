"""Numerical conservation and efficiency checks for declarative pressure changers."""

from pathlib import Path

import pytest
from pyomo.environ import Constraint, value

from multifidelity.model_language import build_model, required_inputs

EXAMPLES = Path(__file__).parents[1] / "examples/model_language"


def set_package(package, pressure, *, enthalpy=None, entropy=None):
    """Populate a configured affine PH or PS state with an analytic solution."""
    water = package.relationship.models.water
    coefficients = {}
    for name, equation in package.relationship.constraints.component_map().items():
        coefficients[name] = value(equation.lower)
        getattr(water.structs.parameters, name).set_value(coefficients[name])
    c = coefficients
    if enthalpy is not None:
        temperature = c['reference_temperature'] + (
            enthalpy - c['reference_enthalpy']
            - (pressure - c['reference_pressure']) / c['density']
        ) / c['heat_capacity']
        entropy = c['reference_entropy'] + c['heat_capacity'] / c['reference_temperature'] * (
            temperature - c['reference_temperature']
        ) - c['thermal_expansion'] / c['density'] * (pressure - c['reference_pressure'])
        state_values = dict(pressure=pressure, enthalpy=enthalpy)
    else:
        temperature = c['reference_temperature'] + c['reference_temperature'] / c['heat_capacity'] * (
            entropy - c['reference_entropy']
            + c['thermal_expansion'] / c['density'] * (pressure - c['reference_pressure'])
        )
        enthalpy = c['reference_enthalpy'] + c['heat_capacity'] * (
            temperature - c['reference_temperature']
        ) + (pressure - c['reference_pressure']) / c['density']
        state_values = dict(pressure=pressure, entropy=entropy)
    for state in (package.structs.state, water.structs.state):
        for name, number in state_values.items():
            getattr(state, name).set_value(number)
    properties = dict(temperature=temperature, entropy=entropy, enthalpy=enthalpy,
                      density=c['density'], heat_capacity=c['heat_capacity'], viscosity=c['viscosity'])
    for block in (package.structs.properties, water.structs.properties):
        for name, number in properties.items():
            if hasattr(block, name):
                getattr(block, name).set_value(number)
    return properties


def assert_balanced(block):
    for equation in block.component_data_objects(Constraint):
        assert value(equation.body) == pytest.approx(value(equation.lower), abs=1e-8), equation.name


@pytest.mark.parametrize('efficiency', [0.65, 1.0])
def test_pump_matches_incompressible_efficiency_and_energy_balance(efficiency):
    model = build_model('pump_flowsheet', EXAMPLES / 'pump_flowsheet.json')
    pump = model.fs.root.relationship.models.pump
    flow, pressure, enthalpy, rise = 2, 300000, 140000, 200000
    work = flow * rise / 997 / efficiency
    pump.structs.parameters.pressure_rise.set_value(rise)
    pump.structs.parameters.efficiency.set_value(efficiency)
    for state, p, h in ((pump.structs.inlet, pressure, enthalpy),
                        (pump.structs.outlet, pressure + rise, enthalpy + work / flow)):
        state.flow.set_value(flow)
        state.pressure.set_value(p)
        state.enthalpy.set_value(h)
    set_package(pump.relationship.models.outlet_state, pressure + rise, enthalpy=enthalpy + work / flow)
    pump.structs.performance.work.set_value(work)
    pump.structs.performance.fluid_work.set_value(work * efficiency)
    assert_balanced(pump)
    pump.structs.performance.work.set_value(work * 1.1)
    with pytest.raises(AssertionError):
        assert_balanced(pump)
    required = required_inputs('pump_flowsheet', EXAMPLES / 'pump_flowsheet.json')
    assert len(required) == 5
    assert 'pump.parameters.efficiency' in required
    assert not any('work' in name for name in required)


@pytest.mark.parametrize('efficiency', [0.65, 1.0])
def test_compressor_matches_isentropic_efficiency_and_energy_balance(efficiency):
    model = build_model('compressor_flowsheet', EXAMPLES / 'compressor_flowsheet.json')
    compressor = model.fs.root.relationship.models.compressor
    flow, pressure, enthalpy, rise = 2, 300000, 140000, 200000
    states = compressor.relationship.models
    inlet = set_package(states.inlet_state, pressure, enthalpy=enthalpy)
    reference = set_package(states.isentropic_state, pressure + rise, entropy=inlet['entropy'])
    isentropic_work = flow * (reference['enthalpy'] - enthalpy)
    work = isentropic_work / efficiency
    actual = set_package(states.outlet_state, pressure + rise, enthalpy=enthalpy + work / flow)
    assert reference['entropy'] == pytest.approx(inlet['entropy'])
    assert actual['entropy'] >= inlet['entropy'] - 1e-9
    if efficiency < 1:
        assert actual['entropy'] > inlet['entropy']
        assert actual['temperature'] > reference['temperature']
    compressor.structs.parameters.pressure_rise.set_value(rise)
    compressor.structs.parameters.efficiency.set_value(efficiency)
    for state, p, h in ((compressor.structs.inlet, pressure, enthalpy),
                        (compressor.structs.outlet, pressure + rise, enthalpy + work / flow)):
        state.flow.set_value(flow)
        state.pressure.set_value(p)
        state.enthalpy.set_value(h)
    compressor.structs.performance.work.set_value(work)
    compressor.structs.performance.isentropic_work.set_value(isentropic_work)
    assert_balanced(compressor)
    required = required_inputs('compressor_flowsheet', EXAMPLES / 'compressor_flowsheet.json')
    assert len(required) == 5
    assert 'compressor.parameters.efficiency' in required
    assert not any('work' in name or 'entropy' in name for name in required)


def test_heat_pump_power_is_calculated_and_aggregate_power_is_internal():
    cycle = required_inputs('heat_pump_flowsheet', EXAMPLES / 'heat_pump_cycle.json')
    aggregate = required_inputs('heat_pump_flowsheet', EXAMPLES / 'heat_pump_aggregate.json')
    assert 'heat_pump.compressor.parameters.pressure_rise' in cycle
    assert 'heat_pump.compressor.parameters.efficiency' in cycle
    assert not any('electrical_power' in name for name in cycle)
    assert 'heat_pump.power_model.parameters.electrical_power' in aggregate


def test_milk_power_specification_can_determine_compressor_pressure_rise():
    """The target influences work through the validated child equations."""
    path = EXAMPLES / 'milk_evaporator_detailed.json'
    build_model('milk_evaporator', path)
    required = required_inputs('milk_evaporator', path)
    assert 'parameters.mvr_power' in required
    assert 'mvr.parameters.efficiency' in required
    assert 'mvr.parameters.pressure_rise' not in required
