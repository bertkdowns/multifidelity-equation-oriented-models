"""Derivative ownership, initial specifications, and real tank simulations."""

from copy import deepcopy
import json
import math

import pytest
from pydantic import ValidationError
from pyomo.dae import ContinuousSet, DerivativeVar
import pyomo.environ as pyo
from pyomo.core.base.units_container import UnitsError
from pyomo.util.check_units import assert_units_consistent

from examples.dynamic_tank.run import fix_inputs, make_tank, simulate
from multifidelity.model_language import (
    Library, build_model, required_initial_values, required_inputs,
)
from multifidelity.model_language.definitions import ModelDocument

TANK_SELECTION = {"model": "tank", "relationship": "mixed"}


def integration_definition(*, differentiate=False):
    return {
        "id": "integrator", "domains": {"time": {"kind": "time"}},
        "structs": {
            "state": {"direction": "input" if differentiate else "output", "variables": {
                "level": {"unit": "m", "dimensions": ["time"]},
            }},
            "signal": {"direction": "output" if differentiate else "input", "variables": {
                "rate": {"unit": "m/s", "dimensions": ["time"]},
            }},
        },
        "relationships": {"integrate": {"derivatives": {
            "evolution": {
                "state": "state.level", "rate": "signal.rate",
                "with_respect_to": "time",
                "determines": "signal.rate" if differentiate else "state.level",
            },
        }}},
    }


def make_library(tmp_path, definition):
    (tmp_path / 'model.json').write_text(json.dumps(definition))
    return Library(tmp_path)


def build_integrator(tmp_path, definition=None, **kwargs):
    definition = definition or integration_definition()
    return build_model(
        "integrator", {"model": "integrator", "relationship": "integrate"},
        library=make_library(tmp_path, definition), **kwargs,
    )


def test_tank_construction_and_specification_discovery():
    assert set(required_initial_values("tank", TANK_SELECTION)) == {
        "inventory.level", "inventory.energy",
    }
    assert 'inventory.energy' not in required_inputs("tank", TANK_SELECTION)
    m = make_tank()
    assert isinstance(m.fs.time, ContinuousSet)
    derivatives = list(m.component_objects(DerivativeVar))
    assert len(derivatives) == 2
    assert derivatives[0].get_state_var() is m.fs.root.structs.inventory.level
    b = m.fs.root.structs
    assert b.inventory.level[0].fixed
    assert b.inventory.energy[0].fixed
    assert not b.inventory.level[1000].fixed
    assert not b.rates.energy[0].fixed
    assert not b.inventory.temperature[0].fixed
    assert_units_consistent(m)


def test_discretization_expands_every_equation_and_preserves_units():
    m = make_tank(horizon=100)
    pyo.TransformationFactory('dae.finite_difference').apply_to(
        m, wrt=m.fs.time, nfe=4, scheme='BACKWARD',
    )
    assert list(m.fs.time) == [0, 25, 50, 75, 100]
    r = m.fs.root.relationship
    assert len(r.constraints.energy_balance) == 5
    assert len(r.derivatives.energy.equation) == 5
    assert len(r.derivatives.energy.coordinate_rate_disc_eq) == 4
    assert not m.fs.root.structs.inventory.energy[25].fixed
    assert_units_consistent(m)


def test_tank_steady_rebuild_has_zero_rates_and_no_initial_fixes():
    dynamic = make_tank()
    steady = make_tank(mode='steady')
    assert not isinstance(steady.fs.time, ContinuousSet)
    assert not list(steady.component_objects(DerivativeVar))
    b = steady.fs.root.structs
    assert not b.inventory.level[0].fixed
    assert not b.inventory.energy[0].fixed
    assert dynamic.fs.root.structs.inventory.level[0].fixed
    b.rates.energy[0].set_value(0)
    assert pyo.value(steady.fs.root.relationship.derivatives.energy.equation[0].body) == 0
    assert_units_consistent(steady)


def test_tank_implicit_simulation_matches_discrete_solution(solver):
    m = simulate(make_tank(), nfe=100)
    b = m.fs.root.structs
    expected = 333.15 - 30 / (1 + 10 / 1000) ** 100
    assert pyo.value(b.inventory.level[1000]) == pytest.approx(1, abs=1e-7)
    assert pyo.value(b.inventory.temperature[1000]) == pytest.approx(expected, abs=1e-5)
    assert pyo.value(b.inventory.temperature[1000]) == pytest.approx(
        333.15 - 30 * math.exp(-1), abs=0.06,
    )
    assert pyo.value(b.rates.energy[0]) == pytest.approx(125400, abs=1e-4)


def test_filling_tank_conserves_mass_and_energy(solver):
    m = make_tank(horizon=100)
    pyo.TransformationFactory('dae.finite_difference').apply_to(
        m, wrt=m.fs.time, nfe=10, scheme='BACKWARD',
    )
    fix_inputs(m, inflow=1.2, outflow=0.8, loss=1000)
    pyo.assert_optimal_termination(solver.solve(m))
    b = m.fs.root.structs
    energy = 125400000
    for t in list(m.fs.time)[1:]:
        mass = 1000 + 0.4 * t
        energy = (energy + 10 * (1.2 * 4180 * 60 - 1000)) / (1 + 10 * 0.8 / mass)
        assert pyo.value(b.inventory.level[t]) == pytest.approx(mass / 1000, abs=1e-7)
        assert pyo.value(b.inventory.energy[t]) == pytest.approx(energy, rel=1e-8)


def test_tank_steady_solve_calculates_withdrawal_and_temperature(solver):
    m = make_tank(mode='steady')
    fix_inputs(m, steady=True, loss=4180)
    pyo.assert_optimal_termination(solver.solve(m))
    b = m.fs.root.structs
    assert pyo.value(b.withdrawal.flow[0]) == pytest.approx(1)
    assert pyo.value(b.inventory.temperature[0]) == pytest.approx(332.15)
    assert pyo.value(b.rates.energy[0]) == pytest.approx(0)


def test_initial_temperature_can_replace_energy(solver):
    m = build_model('tank', TANK_SELECTION, mode='dynamic', domain_values={'time': [0, 100]},
                    initial_values=[
                        {'variable_path': 'inventory.level', 'value': 1},
                        {'variable_path': 'inventory.temperature', 'value': 303.15, 'unit': 'K'},
                    ])
    simulate(m, nfe=10)
    assert not m.fs.root.structs.inventory.energy[0].fixed
    assert pyo.value(m.fs.root.structs.inventory.energy[0]) == pytest.approx(125400000)


def test_tank_petsc_integration(solver):
    from idaes.core.solvers.petsc import petsc_available

    if not petsc_available():
        pytest.skip('IDAES PETSc executable is required')
    m = simulate(make_tank(), backend='petsc', nfe=1)
    b = m.fs.root.structs
    assert pyo.value(b.inventory.level[1000]) == pytest.approx(1, abs=1e-6)
    assert pyo.value(b.inventory.temperature[1000]) == pytest.approx(
        333.15 - 30 * math.exp(-1), abs=1e-3,
    )
    assert not b.inventory.energy[1000].fixed


@pytest.mark.parametrize('time_unit,rate_unit,rate_value,horizon', [
    ('s', 'm/s', 2, 60), ('min', 'm/s', 2, 1), ('s', 'cm/s', 200, 60),
])
def test_time_and_rate_unit_scaling(tmp_path, solver, time_unit, rate_unit, rate_value, horizon):
    definition = integration_definition()
    definition['structs']['signal']['variables']['rate']['unit'] = rate_unit
    m = build_integrator(tmp_path, definition, mode='dynamic', time_unit=time_unit,
                         domain_values={'time': [0, horizon]}, initial_values=[
                             {'variable_path': 'state.level', 'value': 100, 'unit': 'cm'},
                         ])
    pyo.TransformationFactory('dae.finite_difference').apply_to(
        m, wrt=m.fs.time, nfe=4, scheme='BACKWARD',
    )
    m.fs.root.structs.signal.rate.fix(rate_value)
    pyo.assert_optimal_termination(solver.solve(m))
    assert pyo.value(m.fs.root.structs.state.level[horizon]) == pytest.approx(121)
    assert_units_consistent(m)


def test_differentiation_direction_and_uncovered_endpoint(tmp_path, solver):
    definition = integration_definition(differentiate=True)
    library = make_library(tmp_path, definition)
    selection = {'model': 'integrator', 'relationship': 'integrate'}
    assert set(required_initial_values('integrator', selection, library=library)) == {'signal.rate'}
    m = build_integrator(tmp_path, definition, mode='dynamic', domain_values={'time': [0, 10]},
                         initial_values=[{'variable_path': 'signal.rate', 'value': 7}])
    pyo.TransformationFactory('dae.finite_difference').apply_to(
        m, wrt=m.fs.time, nfe=5, scheme='BACKWARD',
    )
    for t in m.fs.time:
        m.fs.root.structs.state.level[t].fix(1 + 2 * t)
    pyo.assert_optimal_termination(solver.solve(m))
    rate = m.fs.root.structs.signal.rate
    assert pyo.value(rate[0]) == 7
    for t in list(m.fs.time)[1:]:
        assert pyo.value(rate[t]) == pytest.approx(2)


@pytest.mark.parametrize('change,message', [
    ('target', 'state or rate'), ('unknown', 'unknown derivative variable'),
    ('child', 'local variable paths'), ('domain', 'indexed time domain'),
    ('dimensions', 'dimensions must match'), ('same', 'different variables'),
    ('duplicate', 'duplicate derivative'), ('double_determination', 'duplicate determination'),
    ('input_target', 'invalid target'),
])
def test_bad_derivative_definitions(tmp_path, change, message):
    d = integration_definition()
    r = d['relationships']['integrate']
    relation = r['derivatives']['evolution']
    if change == 'target':
        relation['determines'] = 'other.x'
    elif change == 'unknown':
        relation['state'] = 'state.missing'
    elif change == 'child':
        relation['state'] = 'child.state.level'
    elif change == 'domain':
        relation['with_respect_to'] = 'missing'
    elif change == 'dimensions':
        d['structs']['signal']['variables']['rate']['dimensions'] = []
    elif change == 'same':
        relation['rate'] = relation['state']
    elif change == 'duplicate':
        r['derivatives']['again'] = deepcopy(relation)
    elif change == 'double_determination':
        r['constraints'] = {'again': {'for_each': {'t': 'time'},
                                     'lhs': 'state.level[t]', 'rhs': '1 * units.m',
                                     'determines': 'state.level[t]'}}
    elif change == 'input_target':
        relation['determines'] = 'signal.rate'
    with pytest.raises(ValueError, match=message):
        build_integrator(tmp_path, d)


@pytest.mark.parametrize('mode', ['steady', 'dynamic'])
def test_derivative_units_validated_in_both_modes(tmp_path, mode):
    d = integration_definition()
    d['structs']['signal']['variables']['rate']['unit'] = 'kg/s'
    with pytest.raises(UnitsError):
        build_integrator(tmp_path, d, mode=mode, domain_values={'time': [0, 1]})


def test_missing_evolution_fails_output_coverage(tmp_path):
    d = integration_definition()
    d['relationships']['integrate']['derivatives'].clear()
    with pytest.raises(ValueError, match='missing output determinations'):
        build_integrator(tmp_path, d)


@pytest.mark.parametrize('kwargs,message', [
    ({'mode': 'unknown'}, 'mode must be'),
    ({'mode': 'dynamic'}, 'at least two time points'),
    ({'mode': 'dynamic', 'domain_values': {'time': [0]}}, 'at least two time points'),
    ({'initial_values': [{'variable_path': 'state.level', 'value': 1}]}, 'only in dynamic mode'),
])
def test_run_mode_validation(tmp_path, kwargs, message):
    with pytest.raises(ValueError, match=message):
        build_integrator(tmp_path, **kwargs)


@pytest.mark.parametrize('spec,message', [
    ({'variable_path': 'missing.level', 'value': 1}, 'Unknown initial variable'),
    ({'variable_path': 'state.level', 'value': 1, 'at': {'time': 0}}, 'non-time dimensions'),
    ({'variable_path': 'state.level', 'value': 1, 'at': {'missing': 0}}, 'non-time dimensions'),
])
def test_initial_specification_validation(tmp_path, spec, message):
    with pytest.raises(ValueError, match=message):
        build_integrator(tmp_path, mode='dynamic', domain_values={'time': [0, 1]},
                         initial_values=[spec])


def test_initial_values_are_optional_during_construction_and_overlap_is_rejected(tmp_path):
    m = build_integrator(tmp_path, mode='dynamic', domain_values={'time': [0, 1]})
    assert not m.fs.root.structs.state.level[0].fixed
    spec = {'variable_path': 'state.level', 'value': 1}
    with pytest.raises(ValueError, match='Overlapping'):
        build_integrator(tmp_path, mode='dynamic', domain_values={'time': [0, 1]},
                         initial_values=[spec, spec])
    spec['value'] = float('nan')
    with pytest.raises(ValidationError):
        build_integrator(tmp_path, mode='dynamic', domain_values={'time': [0, 1]},
                         initial_values=[spec])


def test_bundled_tank_round_trips():
    tank = Library().get('tank')
    assert ModelDocument.model_validate_json(tank.model_dump_json(by_alias=True)) == tank


def test_initial_profiles_with_time_as_second_axis(tmp_path, solver):
    d = integration_definition()
    d['domains']['cells'] = {'kind': 'discrete'}
    for struct in d['structs'].values():
        next(iter(struct['variables'].values()))['dimensions'] = ['cells', 'time']
    m = build_integrator(tmp_path, d, mode='dynamic', domain_values={
        'time': [0, 10], 'cells': ['a', 'b'],
    }, initial_values=[
        {'variable_path': 'state.level', 'at': {'cells': 'a'}, 'value': 1},
        {'variable_path': 'state.level', 'at': {'cells': 'b'}, 'value': 3},
    ])
    pyo.TransformationFactory('dae.finite_difference').apply_to(
        m, wrt=m.fs.time, nfe=2, scheme='BACKWARD',
    )
    m.fs.root.structs.signal.rate.fix(2)
    pyo.assert_optimal_termination(solver.solve(m))
    assert pyo.value(m.fs.root.structs.state.level['a', 10]) == pytest.approx(21)
    assert pyo.value(m.fs.root.structs.state.level['b', 10]) == pytest.approx(23)
    assert not m.fs.root.structs.state.level['a', 5].fixed
    assert_units_consistent(m)


def test_nested_derivative_and_initial_paths(tmp_path):
    child = integration_definition()
    parent = deepcopy(child)
    parent['id'] = 'parent'
    parent['relationships'] = {'wrap': {
        'models': {'integrator': {'model': 'integrator', 'domain_bindings': {'time': 'time'}}},
        'connections': {
            'rate': {'from': 'signal', 'to': 'integrator.signal'},
            'level': {'from': 'integrator.state', 'to': 'state'},
        },
    }}
    (tmp_path / 'parent.json').write_text(json.dumps(parent))
    library = make_library(tmp_path, child)
    selection = {'model': 'parent', 'relationship': 'wrap', 'submodels': {
        'integrator': {'relationship': 'integrate'},
    }}
    assert set(required_initial_values('parent', selection, library=library)) == {
        'integrator.state.level',
    }
    m = build_model('parent', selection, library=library, mode='dynamic',
                    domain_values={'time': [0, 10]}, initial_values=[
                        {'variable_path': 'integrator.state.level', 'value': 2},
                    ])
    nested = m.fs.root.relationship.models.integrator
    assert nested.structs.state.level.index_set() is m.fs.time
    assert nested.structs.state.level[0].fixed
    pyo.TransformationFactory('dae.finite_difference').apply_to(
        m, wrt=m.fs.time, nfe=2, scheme='BACKWARD',
    )
    assert len(nested.relationship.derivatives.evolution.equation) == 3
    assert len(m.fs.root.relationship.connections.level.level) == 3


@pytest.mark.parametrize('spec,message', [
    ({'variable_path': 'parameters.area', 'value': 1}, 'time-indexed'),
    ({'variable_path': 'inventory.level', 'value': -1}, 'outside variable bounds'),
])
def test_invalid_tank_initial_values(spec, message):
    with pytest.raises(ValueError, match=message):
        build_model('tank', TANK_SELECTION, mode='dynamic', domain_values={'time': [0, 1]},
                    initial_values=[spec])


def test_incompatible_initial_units(tmp_path):
    with pytest.raises(UnitsError):
        build_integrator(tmp_path, mode='dynamic', domain_values={'time': [0, 1]},
                         initial_values=[{'variable_path': 'state.level', 'value': 1, 'unit': 'kg'}])
