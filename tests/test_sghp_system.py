"""The same plant wiring supports independent heat-pump representation choices."""

import json
from pathlib import Path

import pytest
from pyomo.core.expr.visitor import identify_variables
from pyomo.environ import Constraint, Var, value
from pyomo.util.check_units import assert_units_consistent

from multifidelity.model_language import Library, build_model, get_variable
from multifidelity.model_language import InformationDocument, apply_specification, select_specification

EXAMPLES = Path(__file__).parents[1] / 'examples/steam_generating_heat_pump_system'


@pytest.mark.parametrize('sghp', ['aggregate', 'cycle'])
@pytest.mark.parametrize('phnix', ['aggregate', 'cycle'])
def test_independent_choices_preserve_plant_connections(sghp, phnix):
    selection = EXAMPLES / f'{sghp}_{phnix}.json'
    model = build_model('steam_generating_heat_pump_system', selection,
                        domain_values={'time': [0, 10]})
    assert_units_consistent(model)
    plant = model.fs.root.relationship
    assert hasattr(plant.models.sghp.relationship.models, 'compressor') == (sghp == 'cycle')
    assert hasattr(plant.models.phnix.relationship.models, 'compressor') == (phnix == 'cycle')
    # Check every plant connection against its actual variable objects, including
    # the three recycles, all three SGHP water circuits, and steam export.
    definition = Library().get('steam_generating_heat_pump_system')
    for name, connection in definition.relationships['flowsheet'].connections.items():
        for field in ['flow', 'pressure', 'enthalpy']:
            source = get_variable(model, f'{connection.from_}.{field}')
            target = get_variable(model, f'{connection.to}.{field}')
            assert source is not target
            for t in model.fs.time:
                equation = getattr(getattr(plant.connections, name), field)[t]
                assert {id(v) for v in identify_variables(equation.body)} == {
                    id(source[t]), id(target[t]),
                }
    assert all(v.value is None and not v.fixed for v in model.component_data_objects(Var))
    for path in ['sghp.hot_outlet.enthalpy', 'sghp.warm_outlet.enthalpy',
                 'sghp.source_outlet.enthalpy', 'phnix.sink_outlet.enthalpy',
                 'performance.electrical_power', 'steam_outlet.flow']:
        assert list(get_variable(model, path)) == [0, 10]


def test_aggregate_sghp_conserves_energy_across_all_three_circuits():
    implementation = json.loads((EXAMPLES / 'aggregate_aggregate.json').read_text())['submodels']['sghp']
    model = build_model('steam_generating_heat_pump_unit', implementation)
    values = {
        'performance.electrical_power': 10000,
        'performance.cop': 4,
        'performance.heating_duty': 40000,
        'performance.hot_water_duty': 35000,
        'performance.warm_water_duty': 5000,
        'performance.cooling_duty': 30000,
        'cop_model.parameters.cop': 4,
        'cop_model.performance.cop': 4,
        'power_model.parameters.electrical_power': 10000,
        'power_model.performance.electrical_power': 10000,
        'warm_water_heater.parameters.heat_duty': 5000,
    }
    for side, outlet_enthalpy in [('hot', 117500), ('warm', 102500), ('source', 85000)]:
        for end in ['inlet', 'outlet']:
            prefix = f'{side}_{end}'
            values[f'{prefix}.flow'] = 2
            values[f'{prefix}.pressure'] = 300000
            values[f'{prefix}.enthalpy'] = 100000 if end == 'inlet' else outlet_enthalpy
    for end in ['inlet', 'outlet']:
        for field in ['flow', 'pressure', 'enthalpy']:
            values[f'warm_water_heater.{end}.{field}'] = values[f'warm_{end}.{field}']
    for path, number in values.items():
        get_variable(model, path)[0].set_value(number)
    for equation in model.component_data_objects(Constraint):
        assert value(equation.body - equation.lower) == pytest.approx(0)
    # Warm-water heating must reduce hot-water duty, rather than being counted twice.
    assert values['performance.hot_water_duty'] + values['performance.warm_water_duty'] == (
        values['performance.cooling_duty'] + values['performance.electrical_power'])


def test_flash_separates_outlet_enthalpies_and_conserves_energy():
    model = build_model('water_flash', {'relationship': 'enthalpy_balance'})
    values = {
        'inlet.flow': 2, 'inlet.pressure': 200000, 'inlet.enthalpy': 700000,
        'parameters.liquid_enthalpy': 500000, 'parameters.vapor_enthalpy': 2500000,
        'liquid.flow': 1.8, 'liquid.pressure': 200000, 'liquid.enthalpy': 500000,
        'vapor.flow': .2, 'vapor.pressure': 200000, 'vapor.enthalpy': 2500000,
    }
    for path, number in values.items():
        get_variable(model, path)[0].set_value(number)
    assert_units_consistent(model)
    for equation in model.component_data_objects(Constraint):
        assert value(equation.body - equation.lower) == pytest.approx(0)


def test_reference_records_have_traceable_sources_and_applicable_paths():
    information = InformationDocument.load_json(EXAMPLES / 'information.json')
    observations = InformationDocument.load_json(EXAMPLES / 'reference_observations.json')
    replay = InformationDocument.load_json(EXAMPLES / 'sghp_replay_information.json')
    reference = json.loads((EXAMPLES / 'ahuora_reference.json').read_text())
    provenance = json.loads((EXAMPLES / 'value_provenance.json').read_text())['records']
    source_ids = {v['id'] for o in reference['objects'] for p in o['properties'] for v in p['values']}
    all_paths = set()
    for sghp in ['aggregate', 'cycle']:
        for phnix in ['aggregate', 'cycle']:
            model = build_model('steam_generating_heat_pump_system',
                                EXAMPLES / f'{sghp}_{phnix}.json')
            all_paths.update(model._model_language_variables)
    assert all(r.variable_path in all_paths for r in information.records + observations.records)
    for record in information.records + observations.records + replay.records:
        assert set(provenance[record.id]['source_property_value_ids']) <= source_ids
        assert record.information_type != 'sensor_reading'
        assert record.standard_deviation is None
    # Keep stale display text separate from captured values and manipulated work
    # separate from independently configured specifications.
    compressor = next(o for o in reference['objects'] if o['id'] == 1670817)
    work = next(p for p in compressor['properties'] if p['key'] == 'work_mechanical')['values'][0]
    assert work['display_value'] == '6'
    assert work['value'] == pytest.approx(2.375729672279988)
    assert work['control_manipulated'] is not None


def test_reference_configuration_is_partial_and_converts_units():
    model = build_model('steam_generating_heat_pump_system', EXAMPLES / 'cycle_aggregate.json')
    information = InformationDocument.load_json(EXAMPLES / 'information.json')
    selection = select_specification(model, information,
                                    prediction_targets=['steam_outlet.flow'])
    assert not selection.complete
    apply_specification(model, selection.specification, information)
    assert value(get_variable(model, 'source_heater.parameters.heat_duty')[0]) == 200
    assert value(get_variable(model, 'phnix.power_model.parameters.electrical_power')[0]) == 25000
    assert value(get_variable(model, 'sghp.condenser.parameters.conductance')) == 30000
    assert not get_variable(model, 'steam_outlet.flow')[0].fixed


def test_captured_sghp_unit_replay_solves_without_fixing_outlets(solver):
    from examples.steam_generating_heat_pump_system.replay import replay
    from pyomo.environ import units

    model, _, outputs = replay(solver)
    observations = InformationDocument.load_json(EXAMPLES / 'reference_observations.json')
    records = {r.variable_path: r for r in observations.records}
    for side in ['source', 'hot', 'warm']:
        for field in ['flow', 'pressure', 'enthalpy']:
            path = f'{side}_outlet.{field}'
            record = records[f'sghp.{path}']
            variable = get_variable(model, path)[0]
            expected = units.convert_value(record.value,
                                           from_units=getattr(units, record.unit),
                                           to_units=units.get_units(variable))
            assert outputs[path] == pytest.approx(expected, rel=1e-8)
            assert not variable.fixed
