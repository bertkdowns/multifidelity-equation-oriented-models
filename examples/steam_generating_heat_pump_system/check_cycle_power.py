"""Control: fixed 15.200054 kW compressor power with free makeup flow."""
import json
from pathlib import Path
from build import build, HERE
from saved_state_guesses import seed_snapshot, refresh_properties
from diagnose_specifications import physical_residuals
from multifidelity.model_language import InformationDocument, SpecificationDocument, apply_specification, get_variable, export_results
from multifidelity.model_language.scaling import apply_scaling, scaled_jacobian, export_scaling
from multifidelity.model_language.selection import _partition
from idaes.core.solvers import get_solver
m=build('cycle','aggregate')
info=InformationDocument.load_json(HERE/'cycle_attempt_information.json')
spec=SpecificationDocument.load_json(HERE/'cycle_attempt_specification.json')
power_id = next(i for i in spec.specifications
                if info.get(i).variable_path == 'sghp.performance.electrical_power')
info = InformationDocument([r.model_copy(update={'value': 15200.05442832877, 'unit': 'W'})
                            if r.id == power_id else r for r in info.records])
apply_specification(m,spec,info)
seed_snapshot(m,HERE/'cycle_specification_relaxation_coherent_results.json')
refresh_properties(m); apply_scaling(m); scaled_jacobian(m); export_scaling(m)
vp,cp=_partition(m)
r={'control_power_W':15200.05442832877,'structural_unmatched_variables':len(vp.unmatched),'structural_unmatched_constraints':len(cp.unmatched),'structural_underconstrained_variables':len(vp.underconstrained),'structural_overconstrained_constraints':len(cp.overconstrained)}
sol=get_solver('ipopt',options={'max_iter':500,'tol':1e-8,'max_cpu_time':60,'nlp_scaling_method':'user-scaling','linear_system_scaling':'none'}).solve(m,tee=True,load_solutions=False)
r['termination']=str(sol.solver.termination_condition)
if len(sol.solution):
 m.solutions.load_from(sol)
 residuals=physical_residuals(m);r['max_scaled_violation']=float(max(x['scaled_violation'] for x in residuals));r['largest_physical_residuals']=residuals[:5]
 r['values']={p:get_variable(m,p)[0].value for p in ['steam_outlet.flow','makeup_state.state.flow','sghp.performance.electrical_power','sghp.performance.cop','sghp.source_inlet.flow']}
export_results(m,status='optimal' if r['termination']=='optimal' and r.get('max_scaled_violation',1)<1e-6 else 'failed',solver='ipopt',termination_condition=r['termination'],specification=spec,message='Control trial: SGHP electrical power fixed at 15.200054 kW.').write_json(HERE/'cycle_power_control_results.json')
(HERE/'cycle_power_control_result.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))
