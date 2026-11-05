import json
import math
import pytest
from pydantic import ValidationError
from pyomo.environ import TransformationFactory
from multifidelity.model_language import (
    Library, ModelDocument, ResultsDocument, build_model, export_results, get_variable,
)


def test_snapshot_roundtrip_identity_units_fixity_and_clone(tmp_path):
    model=build_model('valve',{'relationship':'isenthalpic'})
    pressure=get_variable(model,'inlet.pressure')[0]
    pressure.fix(230000)
    snapshot=export_results(model.clone(),status='optimal',solver='ipopt',termination_condition='optimal',
                            specification={'specifications':['pressure_record']})
    pressure.set_value(100000)
    assert snapshot.model_id=='valve'
    assert snapshot.implementation.relationship=='isenthalpic'
    assert snapshot.solve.status=='optimal'
    entry=next(v for v in snapshot.variables if v.variable_path=='inlet.pressure')
    assert entry.unit=='Pa' and entry.dimensions==('time',)
    assert entry.entries[0].index==(0.0,)
    assert entry.entries[0].fixed and entry.entries[0].value==230000
    path=tmp_path/'results.json';snapshot.write_json(path)
    assert ResultsDocument.load_json(path)==snapshot
    assert not pressure.value==entry.entries[0].value


def test_discretized_grid_is_exported_with_explicit_coordinates():
    model=build_model('valve',{'relationship':'isenthalpic'},mode='dynamic',domain_values={'time':[0,1]})
    TransformationFactory('dae.finite_difference').apply_to(model,wrt=model.fs.time,nfe=4)
    snapshot=export_results(model)
    assert snapshot.mode=='dynamic' and snapshot.time_unit=='s'
    entries=next(v for v in snapshot.variables if v.variable_path=='inlet.pressure').entries
    assert [e.index for e in entries]==[(t,)for t in model.fs.time]
    assert len(entries)==5
    assert snapshot.solve.status=='not_solved'


def test_multidimensional_and_scalar_missing_values():
    library=Library()
    variables={'pressure':{'unit':'Pa','dimensions':['time','zone'],'default':200000},
               'scalar':{'unit':'dimensionless'}}
    library.models['result_grid']=ModelDocument.model_validate({
        'id':'result_grid','domains':{'time':{'kind':'time'},'zone':{'kind':'discrete'}},
        'structs':{'inlet':{'direction':'input','variables':variables},
                   'outlet':{'direction':'output','variables':variables}},
        'relationships':{'copy':{'constraints':{
            'p':{'lhs':'outlet.pressure[t,j]','rhs':'inlet.pressure[t,j]',
                 'determines':'outlet.pressure[t,j]','for_each':{'t':'time','j':'zone'}},
            's':{'lhs':'outlet.scalar','rhs':'inlet.scalar','determines':'outlet.scalar'}}}},
    })
    model=build_model('result_grid',{'relationship':'copy'},library=library,
                      domain_values={'time':[0,10],'zone':['A','B']})
    get_variable(model,'inlet.pressure')[0,'A'].set_value(math.inf,skip_validation=True)
    rows={v.variable_path:v for v in export_results(model,status='failed').variables}
    assert rows['inlet.pressure'].dimensions==('time','zone')
    assert rows['inlet.pressure'].entries[0].index==(0,'A')
    assert rows['inlet.pressure'].entries[0].issue=='nonfinite'
    scalar=rows['inlet.scalar']
    assert scalar.dimensions==() and scalar.entries[0].index==()
    assert scalar.entries[0].value is None and scalar.entries[0].issue=='unset'
    assert 'Infinity' not in export_results(model).model_dump_json()


def test_invalid_results_are_rejected():
    doc=json.loads(export_results(build_model('valve',{'relationship':'isenthalpic'})).model_dump_json())
    for mutate in [lambda d:d.update(schema_version=2),
                   lambda d:d['variables'].append(d['variables'][0]),
                   lambda d:d['variables'][0]['entries'][0].update(index=[True]),
                   lambda d:d['variables'][0]['entries'][0].update(value=None),
                   lambda d:d['variables'][0]['entries'][0].update(fixed='yes'),
                   lambda d:d['variables'][0]['entries'][0].update(value=float('inf'))]:
        candidate=json.loads(json.dumps(doc));mutate(candidate)
        with pytest.raises(ValidationError):ResultsDocument.model_validate(candidate)
