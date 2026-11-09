"""Scaling conventions, unit bridges, and numerical input selection."""
import math

import numpy as np
import pytest
from idaes.core.util.scaling import get_scaling_factor, set_scaling_factor
from pydantic import ValidationError
from pyomo.environ import ConcreteModel, Constraint, Expr_if, TransformationFactory, Var, units

from multifidelity.model_language import (
    Library, ModelDocument, apply_scaling, build_model, get_variable,
    initialize_model, register_standard_providers,
)
from multifidelity.model_language.definitions import Variable
from multifidelity.model_language.scaling import rank_inputs, scaled_jacobian


@pytest.mark.parametrize('factor', [0, -1, math.inf, math.nan])
def test_scale_must_be_finite_positive(factor):
    with pytest.raises(ValidationError):
        Variable(scale=factor)


def test_scales_survive_discretization_and_cloning_without_changing_values():
    model = build_model('valve', {'relationship': 'isenthalpic'}, mode='dynamic',
                        domain_values={'time': [0, 1]})
    TransformationFactory('dae.finite_difference').apply_to(model, wrt=model.fs.time, nfe=4)
    model = model.clone()
    pressure = get_variable(model, 'inlet.pressure')
    pressure[0].fix(200000)
    before = [(v, v.value, v.fixed) for v in model.component_data_objects(Var)]
    apply_scaling(model)
    assert all(get_scaling_factor(v) == 1e-5 for v in pressure.values())
    assert all(v.value == old and v.fixed == fixed for v, old, fixed in before)


def native_model(tmp_path, *, declared=True):
    library = Library(tmp_path)
    variable = {'unit': 'Pa', 'default': 200000}
    if declared:
        variable['scale'] = 1e-5
    library.models['native'] = ModelDocument.model_validate({
        'id': 'native', 'structs': {
            'inlet': {'direction': 'input', 'variables': {'pressure': variable}},
            'outlet': {'direction': 'output', 'variables': {'pressure': {'unit': 'Pa'}}},
        }, 'relationships': {'native': {'external': {
            'provider': 'test', 'dependencies': {'outlet.pressure': ['inlet.pressure']}}}},
    })
    calls = []
    def provider(block, config):
        block.p = Var(initialize=200, units=units.kPa)
        block.q = Var(initialize=200, units=units.kPa)
        block.eq = Constraint(expr=block.q == block.p)
        return {'inlet.pressure': block.p, 'outlet.pressure': block.q}
    def scaler(block, config):
        calls.append(block.name)
        set_scaling_factor(block.p, 0.02)
        set_scaling_factor(block.q, 0.01)
    library.register_provider('test', provider, scaler=scaler)
    return build_model('native', {'relationship': 'native'}, library=library), calls


def test_native_scaler_unit_conversion_and_public_declaration_priority(tmp_path):
    model, calls = native_model(tmp_path)
    clone = model.clone()
    report = apply_scaling(clone)
    native = clone.fs.root.relationship.provider
    assert len(calls) == len(report.callbacks) == 1
    assert get_scaling_factor(native.p) == pytest.approx(0.01)
    assert get_scaling_factor(get_variable(clone, 'outlet.pressure')) == pytest.approx(1e-5)
    assert get_scaling_factor(model.fs.root.relationship.provider.p) is None
    assert native.p.value == 200 and not native.p.fixed


def test_native_scale_can_supply_missing_public_scale(tmp_path):
    model, calls = native_model(tmp_path, declared=False)
    apply_scaling(model)
    assert get_scaling_factor(get_variable(model, 'inlet.pressure')) == pytest.approx(2e-5)


def test_missing_scales_use_one_and_are_reported():
    model = ConcreteModel()
    model.x = Var(initialize=2)
    report = apply_scaling(model)
    assert get_scaling_factor(model.x) == 1
    assert report.fallback_variables == ['x']


def state_problem(*, pressure_unit='Pa', equation_multiplier=1):
    model = ConcreteModel()
    model.pressure = Var(initialize=200000 if pressure_unit == 'Pa' else 200)
    model.enthalpy = Var(initialize=100000)
    model.temperature = Var(initialize=350.15)
    model.density = Var(initialize=1000)
    conversion = 1 if pressure_unit == 'Pa' else 1000
    model.thermo = Constraint(expr=equation_multiplier * (
        model.temperature - 273.15 - model.enthalpy/4200 + conversion*model.pressure*1e-7) == 0)
    model.rho = Constraint(expr=model.density == 1000 + conversion*model.pressure*1e-7)
    model.temperature.fix()
    set_scaling_factor(model.pressure, 1e-5 * conversion)
    set_scaling_factor(model.enthalpy, 1e-5)
    set_scaling_factor(model.temperature, 1/300)
    set_scaling_factor(model.density, 1e-3)
    return model


@pytest.mark.parametrize('pressure_unit,multiplier', [('Pa', 1), ('kPa', 1), ('Pa', 1e8)])
def test_pressure_is_preferred_with_fixed_temperature_independent_of_units(pressure_unit, multiplier):
    model = state_problem(pressure_unit=pressure_unit, equation_multiplier=multiplier)
    candidates = [('enthalpy', None, model.enthalpy), ('pressure', None, model.pressure)]
    ranked, diagnostic = rank_inputs(model, candidates, 1)
    assert ranked[0][0] == 'pressure'
    assert diagnostic['numerical_rank'] == diagnostic['expected_rank'] == 2
    assert diagnostic['nullity'] == 1
    assert diagnostic['candidates'][0]['score'] > 0.99
    assert all(not v.fixed for v in [model.pressure, model.enthalpy, model.density])
    assert model.temperature.fixed


def test_auto_equation_scaling_normalises_jacobian_rows():
    model = state_problem(equation_multiplier=1e8)
    matrix, variables, constraints = scaled_jacobian(model)
    assert np.max(np.abs(matrix), axis=1) == pytest.approx([1, 1])
    assert all(get_scaling_factor(c) > 0 for c in constraints)
    assert model.enthalpy.value == 100000


def test_piecewise_derivative_uses_current_branch():
    model = ConcreteModel()
    model.x = Var(initialize=2)
    model.y = Var(initialize=4)
    model.eq = Constraint(expr=model.y == Expr_if(IF=model.x > 0, THEN=2*model.x, ELSE=-model.x))
    matrix, variables, constraints = scaled_jacobian(model)
    col = {id(v): i for i, v in enumerate(variables)}
    assert matrix[0, col[id(model.x)]] == pytest.approx(-1)
    assert matrix[0, col[id(model.y)]] == pytest.approx(0.5)


def test_numerical_degeneracy_is_reported_without_extra_fixes(tmp_path):
    library = Library(tmp_path)
    library.models['singular'] = ModelDocument.model_validate({
        'id': 'singular', 'structs': {
            'inlet': {'direction': 'input', 'variables': {'x': {'default': 0}}},
            'outlet': {'direction': 'output', 'variables': {'y': {'default': 0}}},
        }, 'relationships': {'eq': {'constraints': {
            'eq': {'lhs': 'outlet.y ** 2', 'rhs': 'inlet.x ** 2', 'determines': 'outlet.y'}}}},
    })
    library.models['wrapper'] = ModelDocument.model_validate({
        'id': 'wrapper', 'structs': {}, 'relationships': {'eq': {
            'models': {'child': {'model': 'singular'}}, 'constraints': {
                'input': {'lhs': 'child.inlet.x', 'rhs': '1', 'determines': 'child.inlet.x'}}}},
    })
    model = build_model('wrapper', {'relationship': 'eq', 'submodels': {
        'child': {'relationship': 'eq'}}}, library=library)
    result = initialize_model(model)
    assert not result.success
    stage = result.stages[0]
    assert stage.status == 'numerical_rank_deficient'
    assert stage.temporary_fixes == []
    assert stage.numerical_selections[0]['numerical_rank'] == 0
    assert all(not v.fixed for v in model.component_data_objects(Var))


def test_helmholtz_temperature_specification_leaves_enthalpy_free(solver):
    from idaes.models.properties.general_helmholtz import helmholtz_available
    if not helmholtz_available():
        pytest.skip('Helmholtz functions unavailable')
    library = Library()
    register_standard_providers(library)
    from multifidelity.model_language.definitions import Constraint as ModelConstraint
    library.models['helmholtz_water_state_block'].relationships['evaluate'].constraints['pressure'] = ModelConstraint(
        lhs='states.state.pressure[t]', rhs='200000 * units.Pa',
        determines='states.state.pressure[t]', for_each={'t': 'time'})
    model = build_model('helmholtz_water_state_block', {'relationship': 'evaluate', 'submodels': {
        'states': {'relationship': 'evaluate', 'submodels': {'fluid': {'relationship': 'helmholtz'}}},
    }}, library=library)
    from multifidelity.model_language import InformationDocument, apply_specification
    information = InformationDocument([dict(
        id='temperature', tag='temperature', information_type='assumption',
        variable_path='states.properties.temperature', value=350.15, unit='K', trust_rank=5)])
    apply_specification(model, {'specifications': ['temperature'],
                                'replacements': {'temperature': 'states.state.enthalpy'}}, information)
    get_variable(model, 'states.state.flow')[0].fix(1)
    # The water leaf has its own PH guesses; the parent must invert enthalpy at
    # fixed temperature rather than freeze the leaf's 100 kJ/kg guess.
    result = initialize_model(model, solver=solver)
    assert result.success, result
    state_stage = next(s for s in result.stages if s.model_path == 'states')
    assert [f['variable_path'] for f in state_stage.temporary_fixes] == ['states.state.pressure']
    assert not get_variable(model, 'states.state.pressure')[0].fixed
    assert get_variable(model, 'states.state.enthalpy')[0].value == pytest.approx(322500, abs=2000)
    assert not get_variable(model, 'states.state.enthalpy')[0].fixed
    assert result.scaling_callbacks
