"""The same plant wiring supports independent heat-pump representation choices."""

import json
from pathlib import Path

import pytest
from pyomo.core.expr.visitor import identify_variables
from pyomo.environ import Constraint, Var, value
from pyomo.util.check_units import assert_units_consistent

from multifidelity.model_language import Library, build_model as _build_model, get_variable, register_standard_providers
from multifidelity.model_language import InformationDocument, apply_specification, select_specification

EXAMPLES = Path(__file__).parents[1] / 'examples/steam_generating_heat_pump_system'


def build_model(*args, **kwargs):
    library = kwargs.pop('library', None) or Library()
    register_standard_providers(library)
    return _build_model(*args, library=library, **kwargs)


@pytest.mark.parametrize('sghp', ['aggregate', 'cycle'])
@pytest.mark.parametrize('phnix', ['aggregate', 'cycle'])
def test_independent_choices_preserve_plant_connections(sghp, phnix):
    selection = EXAMPLES / f'{sghp}_{phnix}.json'
    model = build_model('steam_generating_heat_pump_system', selection,
                        domain_values={'time': [0, 10]})
    assert_units_consistent(model)
    plant = model.fs.root.relationship
    assert not hasattr(plant.models, 'source_heater')
    connection = Library().get('steam_generating_heat_pump_system').relationships['flowsheet'].connections['source_evaporator_feed']
    assert connection.from_ == 'source_mass_recycle.outlet'
    recycle_feed = Library().get('steam_generating_heat_pump_system').relationships['flowsheet'].connections['source_mass_recycle_feed']
    assert recycle_feed.from_ == 'phnix.sink_outlet'
    assert recycle_feed.to == 'source_mass_recycle.inlet'
    assert connection.to == 'sghp.source_inlet'
    assert hasattr(plant.models.sghp.relationship.models, 'compressor') == (sghp == 'cycle')
    assert hasattr(plant.models.phnix.relationship.models, 'compressor') == (phnix == 'cycle')
    if sghp == 'cycle':
        cycle = Library().get('steam_generating_heat_pump_unit').relationships['cycle']
        assert cycle.connections['link_22'].to == 'refrigerant_mass_recycle.inlet'
        feed = cycle.connections['refrigerant_compressor_feed']
        assert feed.from_ == 'refrigerant_mass_recycle.outlet'
        assert feed.to == 'compressor.inlet'
        recycle = plant.models.sghp.relationship.models.refrigerant_mass_recycle
        # The cut preserves pressure/enthalpy while a separate free input defines
        # refrigerant flow; it must not reintroduce the closed continuity row.
        flow = recycle.relationship.constraints.flow[0]
        assert {id(v) for v in identify_variables(flow.body)} == {
            id(recycle.structs.outlet.flow[0]),
            id(recycle.structs.flow_definition.flow[0]),
        }
        assert not recycle.structs.flow_definition.flow[0].fixed
    # Check every plant connection against its actual variable objects, including
    # the three recycles, all three SGHP water circuits, and steam export.
    definition = Library().get('steam_generating_heat_pump_system')
    assert not any(struct.direction == 'input' for struct in definition.structs.values())
    for name in ['makeup_state', 'phnix_source_state', 'cooling_water_state']:
        assert set(definition.relationships['flowsheet'].models[name].model_arguments) == {'FluidProperties'}
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
    assert all(not v.fixed
               for family in model._model_language_variables.values() for v in family.values())
    assert get_variable(model, 'source_pump.outlet_state.properties.density')[0].value > 0
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
    for side in ['source', 'hot', 'warm']:
        for field in ['flow', 'pressure', 'enthalpy']:
            values[f'{side}_inlet_state.state.{field}'] = values[f'{side}_inlet.{field}']
    for path, number in values.items():
        get_variable(model, path)[0].set_value(number)
    blocks = [model.fs.root.relationship.constraints]
    blocks += [getattr(model.fs.root.relationship.models, n).relationship
               for n in ['cop_model', 'power_model', 'warm_water_heater']]
    for block in blocks:
        for equation in block.component_data_objects(Constraint):
            assert value(equation.body - equation.lower) == pytest.approx(0)
    # Warm-water heating must reduce hot-water duty, rather than being counted twice.
    assert values['performance.hot_water_duty'] + values['performance.warm_water_duty'] == (
        values['performance.cooling_duty'] + values['performance.electrical_power'])


def test_flash_separates_outlet_enthalpies_and_conserves_energy(solver):
    from examples.steam_generating_heat_pump_system.replay import replay_flash

    model, _, _ = replay_flash({'hot_outlet.flow': 2, 'hot_outlet.enthalpy': 700000}, solver)
    assert_units_consistent(model)
    liquid_h = value(get_variable(model, 'flash_separator.liquid.enthalpy')[0])
    vapor_h = value(get_variable(model, 'flash_separator.vapor.enthalpy')[0])
    assert vapor_h > liquid_h
    liquid_flow = value(get_variable(model, 'flash_separator.liquid.flow')[0])
    vapor_flow = value(get_variable(model, 'flash_separator.vapor.flow')[0])
    assert liquid_flow + vapor_flow == pytest.approx(2)
    assert liquid_flow * liquid_h + vapor_flow * vapor_h == pytest.approx(1400000)
    assert value(get_variable(model, 'flash_separator.liquid_properties.vapor_fraction')[0]) == pytest.approx(0, abs=1e-7)
    assert value(get_variable(model, 'flash_separator.vapor_properties.vapor_fraction')[0]) == pytest.approx(1, abs=1e-7)



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
    compressor = next(o for o in reference['objects'] if o['id'] == 1671777)
    work = next(p for p in compressor['properties'] if p['key'] == 'work_mechanical')['values'][0]
    assert work['display_value'] == '12.98'
    assert work['value'] == pytest.approx(12.755835603752978)
    assert work['control_manipulated'] is not None


def test_reference_configuration_is_partial_and_converts_units():
    model = build_model('steam_generating_heat_pump_system', EXAMPLES / 'cycle_aggregate.json')
    information = InformationDocument.load_json(EXAMPLES / 'information.json')
    selection = select_specification(model, information,
                                    prediction_targets=['steam_outlet.flow'])
    assert not selection.complete
    apply_specification(model, selection.specification, information)
    assert not hasattr(model.fs.root.relationship.models, 'source_heater')
    # A partial selector can choose different independent references after a
    # topology change. Check conversion for the records actually selected.
    selected_paths = {information.get(i).variable_path for i in selection.specification.specifications}
    expected = {
        'phnix.power_model.parameters.electrical_power': 27328.1092732687,
        'sghp.condenser.parameters.conductance': 35462.01923747691,
        'phnix.sink_inlet.pressure': 200000,
    }
    assert selected_paths.intersection(expected)
    for path, converted in expected.items():
        family = get_variable(model, path)
        variable = next(iter(family.values()))
        if path in selected_paths:
            assert variable.fixed and variable.value == pytest.approx(converted)
        else:
            assert not variable.fixed
    assert not get_variable(model, 'steam_outlet.flow')[0].fixed


def test_captured_sghp_unit_replay_solves_without_fixing_outlets(solver):
    from examples.steam_generating_heat_pump_system.replay import replay
    from pyomo.environ import units

    model, _, outputs = replay(solver)
    observations = InformationDocument.load_json(EXAMPLES / 'reference_observations.json')
    records = {r.variable_path: r for r in observations.records}
    assert value(get_variable(model, 'source_inlet_state.properties.temperature')[0]) == pytest.approx(350.15)
    assert not get_variable(model, 'source_inlet.enthalpy')[0].fixed
    for side in ['source', 'hot', 'warm']:
        for field in ['flow', 'pressure', 'enthalpy']:
            path = f'{side}_outlet.{field}'
            record = records[f'sghp.{path}']
            variable = get_variable(model, path)[0]
            expected = units.convert_value(record.value,
                                           from_units=getattr(units, record.unit),
                                           to_units=units.get_units(variable))
            if side == 'source' and field == 'pressure':
                expected = 200000
            elif side == 'source' and field == 'enthalpy':
                expected = 316450.5530466966
            assert outputs[path] == pytest.approx(expected, rel=1e-5)
            assert not variable.fixed


def test_reference_flash_replay_produces_steam_from_solved_hot_water(solver):
    from examples.steam_generating_heat_pump_system.replay import replay, replay_flash

    _, _, hot_water = replay(solver)
    model, _, outputs = replay_flash(hot_water, solver)
    assert outputs['steam_flow_kg_h'] == pytest.approx(72.95012685610243, rel=2e-3)
    assert outputs['condensate_flow_kg_s'] == pytest.approx(0.8101999266073179, rel=1e-4)
    assert outputs['condensate_flow_kg_s'] + outputs['steam_flow_kg_h'] / 3600 == pytest.approx(hot_water['hot_outlet.flow'])
    assert not get_variable(model, 'flash_separator.vapor.flow')[0].fixed
    checks = json.loads((EXAMPLES / 'reference_checks.json').read_text())
    assert checks['source']['id'] == 2450
    assert checks['steam_mass_flow_kg_s'] * 3600 == pytest.approx(outputs['steam_flow_kg_h'], rel=2e-3)



def test_phase_routing_can_send_both_phases_to_either_outlet(solver):
    from examples.steam_generating_heat_pump_system.replay import replay_flash

    model, _, _ = replay_flash({'hot_outlet.flow': 2, 'hot_outlet.enthalpy': 700000},
                               solver, phase_fractions=(.8, .25))
    flash = model.fs.root.relationship.models.flash_separator
    flow = value(flash.structs.inlet.flow[0])
    x = value(flash.relationship.models.inlet_state.structs.properties.vapor_fraction[0])
    first_flow = value(flash.structs.liquid.flow[0])
    first_x = value(flash.structs.liquid_properties.vapor_fraction[0])
    second_flow = value(flash.structs.vapor.flow[0])
    second_x = value(flash.structs.vapor_properties.vapor_fraction[0])
    for feed, first, second, fraction in [
        (flow*(1-x), first_flow*(1-first_x), second_flow*(1-second_x), .8),
        (flow*x, first_flow*first_x, second_flow*second_x, .25),
    ]:
        assert first == pytest.approx(feed * fraction, abs=1e-7)
        assert first + second == pytest.approx(feed, abs=1e-7)
    for outlet in ['liquid', 'vapor']:
        assert 0 < value(get_variable(model, 'flash_separator.' + outlet + '_properties.vapor_fraction')[0]) < 1
