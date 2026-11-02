"""The shipped library shares one time domain in steady and dynamic contexts."""

import json
from pathlib import Path

import pytest
import pyomo.environ as pyo
from pyomo.core.expr.visitor import identify_variables
from pyomo.util.check_units import assert_units_consistent

from multifidelity.model_language import Library, build_model, register_standard_providers, required_inputs

EXAMPLES = Path(__file__).parents[1] / 'examples/model_language'
SELECTIONS = sorted(p for p in EXAMPLES.glob('*.json') if p.name != 'milk_evaporator_aggregate.json')


def require_dependencies(model, selection):
    relationship = model.relationships[selection['relationship']]
    external = relationship.definition.external
    if external and external.provider in {'standard.helmholtz_ph', 'standard.humid_air'}:
        pytest.importorskip('ahuora_property_packages')
        if external.provider == 'standard.helmholtz_ph':
            from idaes.models.properties.general_helmholtz import helmholtz_available
            if not helmholtz_available():
                pytest.skip('IDAES Helmholtz compiled functions are required')
    for alias, child in relationship.models.items():
        require_dependencies(child, selection.get('submodels', {})[alias])


@pytest.mark.parametrize('path', SELECTIONS, ids=lambda p: p.stem)
@pytest.mark.parametrize('mode', ['steady', 'dynamic'])
def test_every_example_uses_shared_time_and_expands(path, mode):
    selection = json.loads(path.read_text())
    library = Library()
    register_standard_providers(library)
    require_dependencies(library.resolve(selection['model']), selection)
    m = build_model(selection['model'], selection, library=library, mode=mode,
                    domain_values={'time': [0, 10]})
    if mode == 'dynamic':
        pyo.TransformationFactory('dae.finite_difference').apply_to(
            m, wrt=m.fs.time, nfe=2, scheme='BACKWARD',
        )
    assert_units_consistent(m)
    for v in m.component_objects(pyo.Var):
        if '.structs.' not in v.name or not v.is_indexed():
            continue
        assert v.index_set() is m.fs.time
        assert list(v) == list(m.fs.time)
        assert all(not x.fixed for x in v.values())
    # Input discovery still describes families, independent of numerical points.
    assert required_inputs(selection['model'], selection, library=library) is not None


def test_library_operating_interfaces_and_fixed_coefficients():
    library = Library()
    assert len(library.models) >= 32
    for name, model in library.models.items():
        assert model.domains['time'].kind == 'time'
        for sid, struct in model.structs.items():
            for field, variable in struct.variables.items():
                fixed = (name in {'water_state', 'water_state_ph', 'water_state_ps', 'tank'}
                         and sid == 'parameters') or (
                             name == 'heat_exchanger' and sid == 'parameters' and field == 'conductance'
                         )
                assert variable.dimensions == ([] if fixed else ['time']), (name, sid, field)
        for parameter in model.model_parameters.values():
            for struct in parameter.requires.values():
                assert all(v.dimensions == ['time'] for v in struct.variables.values())


def test_steady_valve_slices_are_independent():
    m = build_model('valve', {'model': 'valve', 'relationship': 'isenthalpic'},
                    domain_values={'time': [0, 1]})
    b = m.fs.root
    for t, flow in [(0, 2), (1, 5)]:
        b.structs.inlet.flow[t].set_value(flow)
        b.structs.outlet.flow[t].set_value(flow)
        equation = b.relationship.constraints.mass_balance[t]
        assert pyo.value(equation.body) == 0
        assert {id(v) for v in identify_variables(equation.body)} == {
            id(b.structs.inlet.flow[t]), id(b.structs.outlet.flow[t]),
        }


def test_property_coefficients_are_shared_across_time():
    selection = json.loads((EXAMPLES / 'water_property_package_constant_properties.json').read_text())
    m = build_model('water_property_package', selection, mode='dynamic', domain_values={'time': [0, 10]})
    pyo.TransformationFactory('dae.finite_difference').apply_to(m, wrt=m.fs.time, nfe=2)
    b = m.fs.root.relationship.models.water
    assert not b.structs.parameters.heat_capacity.is_indexed()
    assert len(m.fs.root.relationship.constraints.heat_capacity) == 1
    for t in m.fs.time:
        variables = list(identify_variables(b.relationship.constraints.temperature[t].body))
        assert any(v is b.structs.parameters.heat_capacity for v in variables)


def test_dynamic_map_drives_energy_accumulator(tmp_path, solver):
    definition = {
        'id': 'meter', 'domains': {'time': {'kind': 'time'}},
        'structs': {
            'inventory': {'direction': 'output', 'variables': {'energy': {'unit': 'J', 'dimensions': ['time']}}},
            'rates': {'direction': 'output', 'variables': {'power': {'unit': 'W', 'dimensions': ['time']}}},
        },
        'relationships': {'metered': {
            'models': {'map': {'model': 'en12900_compressor_map', 'domain_bindings': {'time': 'time'}}},
            'constraints': {'power': {
                'for_each': {'t': 'time'}, 'lhs': 'rates.power[t]',
                'rhs': 'map.performance.electrical_power[t]', 'determines': 'rates.power[t]',
            }},
            'derivatives': {'energy': {
                'state': 'inventory.energy', 'rate': 'rates.power',
                'with_respect_to': 'time', 'determines': 'inventory.energy',
            }},
        }},
    }
    library = Library()
    from multifidelity.model_language.definitions import ModelDocument
    library.models['meter'] = ModelDocument.model_validate(definition)
    register_standard_providers(library)
    m = build_model('meter', {'model': 'meter', 'relationship': 'metered',
                              'submodels': {'map': {'relationship': 'cooling_60rps'}}},
                    library=library, mode='dynamic', domain_values={'time': [0, 10]},
                    initial_values=[{'variable_path': 'inventory.energy', 'value': 0}])
    pyo.TransformationFactory('dae.finite_difference').apply_to(
        m, wrt=m.fs.time, nfe=2, scheme='BACKWARD',
    )
    mapped = m.fs.root.relationship.models.map
    mapped.structs.temperatures.evaporating.fix(280.35)
    mapped.structs.temperatures.condensing.fix(327.55)
    assert len(mapped.relationship.slices) == 3
    for t in m.fs.time:
        m.fs.root.structs.inventory.energy[t].set_value(883.8508203054206 * t)
    pyo.assert_optimal_termination(solver.solve(m))
    assert pyo.value(m.fs.root.structs.inventory.energy[10]) == pytest.approx(8838.508203054206, rel=1e-7)
    assert mapped.relationship.slices[0].provider is not mapped.relationship.slices[5].provider
    assert_units_consistent(m)
