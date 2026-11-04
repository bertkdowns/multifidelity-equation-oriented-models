"""Audit exported scales and inspect the raw primal vector after a failed solve.

Raw AMPL SOL values are diagnostic evidence only. Pyomo intentionally does not
expose them as a solution when IPOPT returns internalSolverError.
"""
import json
import math
from pathlib import Path

from idaes.core.solvers import get_solver
from idaes.core.util.scaling import get_scaling_factor
from pyomo.environ import Var, Constraint
from multifidelity.model_language import InformationDocument, SpecificationDocument, initialize_model
from multifidelity.model_language.scaling import export_scaling
from attempt_solve import build_attempt
from diagnose_specifications import physical_residuals

HERE = Path(__file__).resolve().parent


def load_raw_primal_for_diagnostics(model, solver, result):
    # Private legacy IPOPT/AMPL adapter: deliberately confined to this example.
    lines = Path(solver._soln_file).read_text().splitlines()
    k = lines.index('Options') + 1
    nopts = int(lines[k])
    k += 1
    needs_vbtol = nopts > 4
    if needs_vbtol:
        nopts -= 2
    sizes = list(map(int, lines[k:k+nopts+4]))
    k += nopts + 4 + int(needs_vbtol)
    constraints, variables = sizes[nopts+1], sizes[nopts+3]
    k += constraints
    primal = list(map(float, lines[k:k+variables]))
    if not all(math.isfinite(x) for x in primal):
        raise ValueError('Nonfinite primal vector')
    for i, x in enumerate(primal):
        result._smap.getObject('v'+str(i)).set_value(x, skip_validation=True)


if __name__ == '__main__':
    m = build_attempt()
    init = initialize_model(m,
        information=InformationDocument.load_json(HERE/'attempt_information.json'),
        specification=SpecificationDocument.load_json(HERE/'attempt_specification.json'))
    if init.stages[-1].status != 'numerical_rank_deficient':
        raise RuntimeError('Expected the root numerical-rank stop')
    export_scaling(m.fs.root)
    report = {}
    for kind in (Var, Constraint):
        entries = [dict(name=c.name, factor=get_scaling_factor(c, default=1))
                   for c in m.fs.root.component_data_objects(kind, active=True)]
        report[kind.__name__] = dict(
            invalid=[e for e in entries if not math.isfinite(e['factor']) or e['factor'] <= 0],
            smallest=sorted(entries,key=lambda e:e['factor'])[:10],
            largest=sorted(entries,key=lambda e:-e['factor'])[:10])
    solver = get_solver('ipopt', options={'max_iter':500, 'tol':1e-8,
        'max_cpu_time':60, 'nlp_scaling_method':'user-scaling'})
    result = solver.solve(m, tee=True, load_solutions=False, keepfiles=True)
    report['termination'] = str(result.solver.termination_condition)
    load_raw_primal_for_diagnostics(m, solver, result)
    report['iterate_source'] = 'Raw AMPL SOL primal vector; not an accepted solution'
    rows = physical_residuals(m)
    report['largest_raw_residuals'] = rows[:25]
    report['largest_scaled_residuals'] = sorted(rows,key=lambda r:-r['scaled_violation'])[:25]
    (HERE/'scaling_inspection_result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
