"""Try the whole plant with prescribed flash outlet compositions.

Retain completed child initialization values, then attempt the original full
operating specification without temporary local fixes, even if a local stage fails.
"""
import json
from pathlib import Path
from attempt_solve import build_attempt,HERE
from diagnose_specifications import physical_residuals
from multifidelity.model_language import initialize_model,InformationDocument,SpecificationDocument,get_variable
from multifidelity.model_language.scaling import rank_inputs,export_scaling
from idaes.core.solvers import get_solver
from pyomo.environ import units
m=build_attempt()
r=initialize_model(m,information=InformationDocument.load_json(HERE/'attempt_information.json'),specification=SpecificationDocument.load_json(HERE/'attempt_specification.json'))
_,diag=rank_inputs(m.fs.root,[],0)
export_scaling(m)
s=get_solver('ipopt',options={'max_iter':1000,'max_cpu_time':90,'tol':1e-8,'nlp_scaling_method':'user-scaling','linear_system_scaling':'none'})
r2=s.solve(m,tee=True,load_solutions=False)
report={'initialization_stop':r.failed_model,'initialization_status':r.stages[-1].status,'root_rank':diag,'termination':str(r2.solver.termination_condition),'message':str(r2.solver.message),'solution_returned':bool(len(r2.solution))}
if len(r2.solution):
 m.solutions.load_from(r2)
 report['operating_values']={p:{str(i):dict(value=v.value,unit=str(units.get_units(v)),fixed=v.fixed)for i,v in get_variable(m,p).items()}for p in ['flash_tank.liquid_properties.vapor_fraction','flash_tank.vapor_properties.vapor_fraction','flash_tank.parameters.liquid_to_liquid','flash_tank.parameters.vapor_to_liquid','steam_outlet.flow','sghp.source_inlet.flow','sghp.performance.cop','sghp.performance.electrical_power']}
 rows=physical_residuals(m);report['largest_raw_residuals']=rows[:10];report['largest_scaled_residuals']=sorted(rows,key=lambda r:-r['scaled_violation'])[:10]
(HERE/'attempt_outlet_quality_result.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
