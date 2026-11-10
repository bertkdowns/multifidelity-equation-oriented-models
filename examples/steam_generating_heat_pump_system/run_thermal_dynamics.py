"""PHNIX power-step demonstration with three inventories and selectable SGHP fidelity."""
import argparse
import json
import math
from pathlib import Path

import pyomo.environ as pyo
from idaes.core.solvers import get_solver
from idaes.core.util.model_statistics import degrees_of_freedom
from idaes.core.util.scaling import get_scaling_factor, set_scaling_factor
from pyomo.core.expr.calculus.derivatives import differentiate
from pyomo.core.expr.visitor import identify_variables
from pyomo.util.check_units import assert_units_consistent
from multifidelity.model_language import (
    Library, InformationDocument, InformationRecord, SpecificationDocument,
    build_model, register_standard_providers, pair_specification, apply_specification,
    get_variable, export_results, WorkspaceDocument,
)
from multifidelity.model_language.scaling import apply_scaling, export_scaling, _branch_expression
from multifidelity.model_language.selection import _partition
from saved_state_guesses import refresh_properties
from diagnose_specifications import physical_residuals

HERE = Path(__file__).resolve().parent
LOOPS = {'source_tank': 'source_tank.outlet', 'warm_tank': 'sghp.warm_inlet',
         'hot_tank': 'sghp.hot_inlet'}
DENSITY = {'source_tank': 'phnix.sink_inlet_state.properties.density',
           'warm_tank': 'sghp.warm_inlet_state.properties.density',
           'hot_tank': 'sghp.hot_inlet_state.properties.density'}


def build_case(*, nfe=10, horizon=600, step_time=120, step_fraction=.1, sghp="aggregate", pressure_rise=None):
    snapshot = json.loads((HERE / f'common_{sghp}_aggregate_results.json').read_text())
    steady = {r['variable_path']: r['entries'][0]['value'] for r in snapshot['variables']}
    if sghp == 'cycle' and pressure_rise is None:
        pressure_rise = steady['sghp.compressor.parameters.pressure_rise']
    library = Library(); register_standard_providers(library)
    grid = [horizon*i/nfe for i in range(nfe+1)]
    if not any(abs(t-step_time) < 1e-8 for t in grid):
        raise ValueError('Step time must lie on the time grid')
    model = build_model('steam_generating_heat_pump_system_thermal', HERE / f'thermal_{sghp}.json',
                        library=library, mode='dynamic', domain_values={'time': grid})
    pyo.TransformationFactory('dae.finite_difference').apply_to(
        model, wrt=model.fs.time, nfe=nfe, scheme='BACKWARD')
    assert_units_consistent(model)
    records = list(InformationDocument.load_json(HERE / 'common_operating_information.json').records)
    ids = list(SpecificationDocument.load_json(HERE / 'common_aggregate_aggregate_specification.json').specifications)
    removed = {'attempt_source_tank_adiabatic', 'config_phnix_sink_inlet_pressure',
               'attempt_warm_water_pressure', 'config_phnix_sink_inlet_state_temperature',
               'config_sghp_source_inlet_state_temperature', 'config_sghp_warm_inlet_state_temperature',
               'config_sghp_hot_inlet_flow', 'config_phnix_power_model_parameters_electrical_power'}
    ids = [i for i in ids if i not in removed]
    initial = []
    def add(name, path, number, unit, *, initial_only=False, series=False):
        records.append(InformationRecord(id=name, tag='thermal_demo.'+name,
            information_type='assumption', variable_path=path, value=number, unit=unit,
            type='series' if series else 'constant', trust_rank=8))
        (initial if initial_only else ids).append(name)
    if sghp == 'aggregate':
        add('thermal_sghp_cop', 'sghp.cop_model.parameters.cop', steady['sghp.performance.cop'], 'dimensionless')
    else:
        ids += [f'config_sghp_{name}_parameters_conductance' for name in
                ['condenser','evaporator','subcooler','ihx']]
        ids += ['config_sghp_compressor_parameters_efficiency']
        if pressure_rise is not None:
            add('thermal_sghp_pressure_rise', 'sghp.compressor.parameters.pressure_rise', pressure_rise, 'Pa')
    add('thermal_makeup', 'makeup_state.state.flow', steady['makeup_state.state.flow'], 'kg/s')
    add('thermal_warm_split', 'warm_water_splitter.parameters.fraction', steady['warm_water_splitter.parameters.fraction'], 'dimensionless')
    for alias in ['source_valve', 'warm_water_valve']:
        add('thermal_'+alias+'_dp', alias+'.parameters.pressure_drop', steady[alias+'.parameters.pressure_drop'], 'Pa')
    power = steady['phnix.performance.electrical_power']
    # Backward-Euler inputs describe (t_previous,t]; the first changed sample
    # is strictly after step_time, so the step starts at the declared boundary.
    add('thermal_phnix_power', 'phnix.power_model.parameters.electrical_power',
        [power*(1+step_fraction if t>step_time else 1) for t in model.fs.time], 'W', series=True)
    inventories = {}
    for alias, port in LOOPS.items():
        pressure, enthalpy, flow = (steady[port+'.'+f] for f in ['pressure','enthalpy','flow'])
        mass = steady[DENSITY[alias]] * .1
        energy = mass*enthalpy - pressure*.1
        inventories[alias] = dict(pressure=pressure, enthalpy=enthalpy, flow=flow,
                                 mass=mass, energy=energy, level=.1)
        for suffix, number, unit in [('parameters.area',1,'m**2'),
                                     ('parameters.pressure',pressure,'Pa'),
                                     ('withdrawal.flow',flow,'kg/s'), ('loss.heat',0,'W')]:
            add('thermal_'+alias+'_'+suffix.replace('.','_'),alias+'.'+suffix,number,unit)
        for suffix, number, unit in [('inventory.mass',mass,'kg'),('inventory.energy',energy,'J')]:
            add('initial_'+alias+'_'+suffix.split('.')[-1],alias+'.'+suffix,number,unit,initial_only=True)
    information = InformationDocument(root=tuple(records))
    spec = pair_specification(model, SpecificationDocument(specifications=ids, initial_values=initial), information)
    apply_specification(model,spec,information)
    for path, family in model._model_language_variables.items():
        if path in steady:
            for v in family.values():
                if not v.fixed: v.set_value(steady[path])
    for v in model.component_data_objects(pyo.Var):
        if v.value is None: v.set_value(0 if v.lb is None else max(0,v.lb))
    for alias, inv in inventories.items():
        for t in model.fs.time:
            for suffix, number in [('inventory.mass',inv['mass']),('inventory.energy',inv['energy']),
                                   ('inventory.enthalpy',inv['enthalpy']),('inventory.level',.1),
                                   ('rates.mass',0),('rates.energy',0)]:
                v=get_variable(model,alias+'.'+suffix)[t]
                if not v.fixed: v.set_value(number)
            for port in ['inlet','outlet','inlet_state.state','contents_state.state']:
                for field in ['flow','pressure','enthalpy']:
                    v=get_variable(model,f'{alias}.{port}.{field}')[t]
                    if not v.fixed: v.set_value(inv[field])
    refresh_properties(model)
    apply_scaling(model)
    # Stream each sparse row: do not allocate a dense time-expanded Jacobian.
    for c in model.component_data_objects(pyo.Constraint,active=True):
        expr=_branch_expression(c.body)
        variables=list(identify_variables(expr, include_fixed=False))
        derivatives=differentiate(expr,wrt_list=variables,mode='reverse_symbolic')
        norm=max((abs(pyo.value(d))/get_scaling_factor(v,default=1)
                  for v,d in zip(variables,derivatives,strict=True)),default=0)
        set_scaling_factor(c,1/norm if norm else 1)
    export_scaling(model)
    return model,information,spec,steady,inventories


def run(*, nfe=10, horizon=600, step_time=120, step_fraction=.1, prefix=None, sghp='aggregate', pressure_rise=None):
    model,info,spec,steady,inventories=build_case(nfe=nfe,horizon=horizon,step_time=step_time,step_fraction=step_fraction,sghp=sghp,pressure_rise=pressure_rise)
    prefix = prefix or ('thermal_cycle_step' if sghp == 'cycle' else 'thermal_step')
    if sghp == 'cycle':
        pressure_rise = get_variable(model, 'sghp.compressor.parameters.pressure_rise')[0].value
    vp,cp=_partition(model)
    structure=dict(degrees_of_freedom=degrees_of_freedom(model), unmatched_variables=len(vp.unmatched),
                   unmatched_constraints=len(cp.unmatched), underconstrained=len(vp.underconstrained),
                   overconstrained=len(cp.overconstrained))
    print(structure,flush=True)
    if any(structure.values()):
        print('unmatched variables',[v.name for v in vp.unmatched],flush=True)
        print('unmatched equations',[v.name for v in cp.unmatched],flush=True)
        raise RuntimeError('Dynamic specification is not closed')
    result=get_solver('ipopt',options={'max_iter':500,'tol':1e-8,'max_cpu_time':120,
        'nlp_scaling_method':'user-scaling','linear_system_scaling':'none'}).solve(model,tee=True,load_solutions=False)
    report=dict(sghp=sghp,pressure_rise_Pa=pressure_rise,structure=structure,termination=str(result.solver.termination_condition),
                nfe=nfe,horizon_s=horizon,step_time_s=step_time,step_fraction=step_fraction,
                initial_volume_m3_per_loop=.1,initial_inventories=inventories)
    if len(result.solution):
        model.solutions.load_from(result)
        residuals=physical_residuals(model)
        report['max_scaled_violation']=float(max(r['scaled_violation'] for r in residuals))
        report['largest_physical_residuals']=residuals[:10]
        paths=['source_tank.inventory.temperature','warm_tank.inventory.temperature','hot_tank.inventory.temperature',
               'steam_outlet.flow','phnix.performance.electrical_power','sghp.performance.cop',
               'sghp.performance.heating_duty','sghp.performance.cooling_duty',
               'sghp.performance.hot_water_duty','hot_tank.inventory.mass','source_tank.inventory.mass']
        report['trajectory']=[dict(time_s=float(t),**{p:get_variable(model,p)[t].value for p in paths}) for t in model.fs.time]
    report['solved']=bool(report['termination']=='optimal' and report.get('max_scaled_violation',1)<1e-6)
    (HERE/f'{prefix}_information.json').write_text(info.model_dump_json(indent=2)+'\n')
    (HERE/f'{prefix}_specification.json').write_text(spec.model_dump_json(indent=2)+'\n')
    (HERE/f'{prefix}_report.json').write_text(json.dumps(report,indent=2)+'\n')
    snapshot=export_results(model,status='optimal' if report['solved'] else 'failed',solver='ipopt',
        termination_condition=report['termination'],specification=spec,
        message=f'Three initial 100-litre water inventories; aggregate PHNIX, {sghp} SGHP; constant circulation and algebraic flash.')
    snapshot.write_json(HERE/f'{prefix}_results.json')
    WorkspaceDocument.from_results(snapshot,info).write_json(HERE/f'{prefix}_workspace.json')
    print(json.dumps(report,indent=2),flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sghp',choices=['aggregate','cycle'],default='aggregate')
    parser.add_argument('--pressure-rise',type=float,help='Fixed detailed SGHP compressor pressure rise (Pa).')
    parser.add_argument('--nfe',type=int,default=10)
    parser.add_argument('--step-fraction',type=float,default=.1)
    parser.add_argument('--prefix',help='Artifact prefix; defaults to thermal_step or thermal_cycle_step.')
    args=parser.parse_args()
    if args.nfe<1 or not math.isfinite(args.step_fraction) or args.step_fraction<=-1:
        parser.error('Positive nfe and finite step fraction greater than -1 required')
    if args.pressure_rise is not None and (not math.isfinite(args.pressure_rise) or args.pressure_rise<=0):
        parser.error('Compressor pressure rise must be finite and positive')
    report=run(nfe=args.nfe,step_fraction=args.step_fraction,prefix=args.prefix,sghp=args.sghp,pressure_rise=args.pressure_rise)
    raise SystemExit(0 if report['solved'] else 1)
