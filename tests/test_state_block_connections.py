"""Child inputs are readable connection sources without being supplied by that use."""

from copy import deepcopy

import pytest
from pyomo.environ import Var, assert_optimal_termination, value
from pyomo.util.check_units import assert_units_consistent

from multifidelity.model_language import Library, build_model, get_variable, required_inputs
from multifidelity.model_language.definitions import Connection, ModelDocument


@pytest.fixture
def state_example():
    library = Library()
    output = library.get('state_block').structs['state'].model_dump()
    output['direction'] = 'output'
    library.models['state_example'] = ModelDocument.model_validate({
        'id': 'state_example',
        'domains': {'time': {'kind': 'time'}},
        'structs': {'state': output},
        'relationships': {'flowsheet': {
            'models': {
                'source': {
                    'model': 'state_block',
                    'domain_bindings': {'time': 'time'},
                    'model_arguments': {'FluidProperties': {'model': 'water_property_package'}},
                },
                'first': {'model': 'valve', 'domain_bindings': {'time': 'time'}},
                'second': {'model': 'valve', 'domain_bindings': {'time': 'time'}},
            },
            'connections': {
                'first_feed': {'from': 'source.state', 'to': 'first.inlet'},
                'second_feed': {'from': 'source.state', 'to': 'second.inlet'},
                'publish': {'from': 'source.state', 'to': 'state'},
            },
        }},
    })
    implementation = {'relationship': 'flowsheet', 'submodels': {
        'source': {'relationship': 'evaluate', 'submodels': {
            'fluid': {'relationship': 'constant_properties', 'submodels': {
                'water': {'relationship': 'constant_properties'},
            }},
        }},
        'first': {'relationship': 'isenthalpic'},
        'second': {'relationship': 'isenthalpic'},
    }}
    return library, implementation


def test_child_input_can_supply_multiple_inputs_and_parent_output(state_example):
    library, implementation = state_example
    assert set(required_inputs('state_example', implementation, library=library)) == {
        'source.state.flow',
        'source.state.pressure',
        'source.state.enthalpy',
        'first.parameters.pressure_drop',
        'second.parameters.pressure_drop',
    }
    # Using a source does not mark it supplied; only connection destinations are supplied.
    model = build_model('state_example', implementation, library=library,
                        domain_values={'time': [0, 10]})
    assert_units_consistent(model)
    assert list(get_variable(model, 'source.state.pressure')) == [0, 10]
    assert not get_variable(model, 'source.state.pressure')[0].fixed


@pytest.mark.parametrize('specification_path', ['source.state', 'state'])
def test_direct_state_temperature_specification_determines_connected_enthalpy(state_example, solver, specification_path):
    library, implementation = state_example
    model = build_model('state_example', implementation, library=library)
    get_variable(model, specification_path + '.flow')[0].fix(2)
    get_variable(model, specification_path + '.pressure')[0].fix(200000)
    get_variable(model, 'source.properties.temperature')[0].fix(330.15)
    for valve in ['first', 'second']:
        get_variable(model, valve + '.parameters.pressure_drop')[0].fix(1000)
    # Coefficients are equation-defined variables; avoid zero initial denominators.
    for variable in model.component_data_objects(Var):
        if variable.value is None:
            variable.set_value(1)
    assert_optimal_termination(solver.solve(model))
    expected_enthalpy = 104920.1198085 + 4180 * 32 + (200000 - 101325) / 997
    for prefix in ['source.state', 'state', 'first.inlet', 'second.inlet']:
        assert value(get_variable(model, prefix + '.flow')[0]) == pytest.approx(2)
        assert value(get_variable(model, prefix + '.pressure')[0]) == pytest.approx(200000)
        assert value(get_variable(model, prefix + '.enthalpy')[0]) == pytest.approx(expected_enthalpy)
    for valve in ['first', 'second']:
        assert value(get_variable(model, valve + '.outlet.pressure')[0]) == pytest.approx(199000)
        assert value(get_variable(model, valve + '.outlet.enthalpy')[0]) == pytest.approx(expected_enthalpy)


@pytest.mark.parametrize('operation', [build_model, required_inputs])
@pytest.mark.parametrize('change', ['child_output_target', 'parent_input_target', 'duplicate', 'self'])
def test_readable_child_inputs_preserve_connection_validation(state_example, operation, change):
    library, implementation = state_example
    definition = library.get('state_example')
    connections = definition.relationships['flowsheet'].connections
    expected = 'invalid connection direction'
    if change == 'child_output_target':
        connections['first_feed'].to = 'first.outlet'
    elif change == 'parent_input_target':
        definition.structs['input'] = deepcopy(library.get('state_block').structs['state'])
        connections['publish'].to = 'input'
    elif change == 'parent_output_source':
        connections['first_feed'].from_ = 'state'
    elif change == 'duplicate':
        connections['duplicate'] = deepcopy(connections['first_feed'])
        expected = 'duplicate determination'
    else:
        connections['self'] = Connection(from_='source.state', to='source.state')
        expected = 'connection endpoints must differ'
    with pytest.raises(ValueError, match=expected):
        operation('state_example', implementation, library=library)


def test_parent_output_is_readable_as_a_connection_source(state_example):
    library, implementation = state_example
    library.get('state_example').relationships['flowsheet'].connections['first_feed'].from_ = 'state'
    build_model('state_example', implementation, library=library)
    assert 'source.state.enthalpy' in required_inputs('state_example', implementation, library=library)
