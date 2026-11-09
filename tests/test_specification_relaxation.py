import pytest
from pyomo.environ import value
from pyomo.util.check_units import assert_units_consistent
from idaes.core.solvers import get_solver
from pyomo.opt import check_optimal_termination
from multifidelity.model_language import (
    build_model, InformationDocument, InformationRecord, apply_specification,
    relax_specifications, get_variable, Library, ModelDocument,
)


def setup_problem():
    # Two structurally independent specifications can still conflict with a
    # hard bound. Unlike fixing both ends of a continuity equality, this uses
    # distinct canonical slots and remains a valid replacement document.
    library = Library()
    definition = library.get('valve').model_dump(by_alias=True)
    definition['structs']['parameters']['variables']['offset'] = {
        'unit': 'kg/s', 'dimensions': ['time'], 'bounds': {'min': 0, 'max': 0}}
    definition['relationships']['isenthalpic']['constraints']['mass_balance']['rhs'] = 'inlet.flow[t] + parameters.offset[t]'
    library.models['valve'] = ModelDocument.model_validate(definition)
    model = build_model('valve', {'relationship': 'isenthalpic'}, library=library)
    information = InformationDocument([
        InformationRecord(id='in', variable_path='inlet.flow', value=2, unit='kg/s',
                          information_type='sensor_reading', tag='test', trust_rank=1),
        InformationRecord(id='out', variable_path='outlet.flow', value=3, unit='kg/s',
                          information_type='sensor_reading', tag='test', trust_rank=1),
    ])
    spec = {'specifications': ['in', 'out'], 'replacements': {'out': 'parameters.offset'}}
    apply_specification(model, spec, information)
    for path, val in [('inlet.pressure',200000), ('inlet.enthalpy',100000), ('parameters.pressure_drop',0)]:
        get_variable(model,path)[0].fix(val)
    return model, spec, information


def test_joint_reconciliation_preserves_source_and_units():
    model, spec, info = setup_problem()
    relaxed = relax_specifications(model, spec, info, weights={'in': 3})
    assert_units_consistent(relaxed.model)
    solver=get_solver('ipopt')
    if not solver.available(exception_flag=False):
        pytest.skip('IPOPT unavailable')
    assert check_optimal_termination(solver.solve(relaxed.model))
    rows={r['record_id']:r for r in relaxed.deviations()}
    assert rows['in']['value'] == pytest.approx(2.25)
    assert rows['out']['value'] == pytest.approx(2.25)
    assert value(relaxed.model.specification_relaxation.objective) == pytest.approx(.75)
    for path, target in [('inlet.flow',2),('outlet.flow',3)]:
        original=get_variable(model,path)[0]
        assert original.fixed and original.value == target
    assert get_variable(relaxed.model,'inlet.pressure')[0].fixed


@pytest.mark.parametrize('weights',[{'missing':1},{'in':0},{'in':float('nan')}])
def test_reject_bad_weights(weights):
    m,s,i=setup_problem()
    with pytest.raises(ValueError): relax_specifications(m,s,i,weights=weights)


def test_requires_matching_applied_specification():
    m,s,i=setup_problem()
    get_variable(m,'inlet.flow')[0].fix(1)
    with pytest.raises(ValueError,match='already be applied'):
        relax_specifications(m,s,i)
    assert get_variable(m,'inlet.flow')[0].value==1


def test_declared_scales_change_normalized_penalties():
    from idaes.core.util.scaling import set_scaling_factor
    m,s,i=setup_problem()
    set_scaling_factor(get_variable(m,'inlet.flow')[0],2)
    relaxed=relax_specifications(m,s,i)
    solver=get_solver('ipopt')
    if not solver.available(exception_flag=False):
        pytest.skip('IPOPT unavailable')
    assert check_optimal_termination(solver.solve(relaxed.model))
    rows={r['record_id']:r for r in relaxed.deviations()}
    assert rows['in']['value']==pytest.approx(2.2)
    assert rows['in']['scaled_deviation']==pytest.approx(.4)
    assert rows['out']['value']==pytest.approx(2.2)


def test_record_units_convert_and_bounds_are_retained():
    m,s,i=setup_problem()
    info=InformationDocument([InformationRecord(
        id='pressure',tag='p',trust_rank=1,information_type='sensor_reading',
        variable_path='outlet.pressure',value=200,unit='kPa')])
    get_variable(m, 'parameters.pressure_drop').unfix()
    spec={'specifications':['pressure'], 'replacements': {'pressure': 'parameters.pressure_drop'}}
    pressure=get_variable(m,'outlet.pressure')[0]
    pressure.setlb(100000)
    apply_specification(m,spec,info)
    relaxed=relax_specifications(m,spec,info)
    assert relaxed.entries[0]['target']==200000
    assert get_variable(relaxed.model,'outlet.pressure')[0].lb==100000
    assert pressure.fixed
