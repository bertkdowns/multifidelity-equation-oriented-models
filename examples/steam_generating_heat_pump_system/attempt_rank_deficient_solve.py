"""Attempt the root solve despite numerical rank deficiency at its initial guess.

Run from the repository root using .venv/bin/python and this file's path.
The normal initializer's rank check is unchanged; this explicit experiment runs
IPOPT only after all component stages have initialized and the root rank check fails.
"""
import json
from pathlib import Path

from idaes.core.solvers import get_solver
from pyomo.environ import Var
from pyomo.opt import check_optimal_termination
from multifidelity.model_language import InformationDocument, SpecificationDocument, initialize_model
from multifidelity.model_language.hierarchical_initialization import _constraint_violation, _valid_guess
from multifidelity.model_language.scaling import export_scaling
from attempt_solve import build_attempt

HERE = Path(__file__).resolve().parent

if __name__ == '__main__':
    model = build_attempt()
    solver = get_solver('ipopt', options={'max_iter': 500, 'tol': 1e-8, 'max_cpu_time': 60})
    initialized = initialize_model(
        model, solver=solver,
        information=InformationDocument.load_json(HERE / 'attempt_information.json'),
        specification=SpecificationDocument.load_json(HERE / 'attempt_specification.json'),
    )
    root = initialized.stages[-1]
    if (initialized.failed_model != 'steam_generating_heat_pump_system'
            or root.status != 'numerical_rank_deficient'
            or any(s.status != 'initialized' for s in initialized.stages[:-1])):
        raise RuntimeError('Expected only the final root numerical-rank check to fail')
    report = {
        'initialized_component_stages': len(initialized.stages) - 1,
        'initial_rank_diagnostic': root.numerical_selections[-1],
        'initial_max_scaled_constraint_violation': _constraint_violation(model.fs.root, scaled=True),
        'operating_specifications_changed': False,
    }
    export_scaling(model.fs.root)
    try:
        result = solver.solve(model.fs.root, tee=True, load_solutions=False,
                              options={'nlp_scaling_method': 'user-scaling'})
        report['solver_status'] = str(result.solver.status)
        report['termination_condition'] = str(result.solver.termination_condition)
        report['solver_message'] = str(result.solver.message)
        report['solution_loaded'] = bool(len(result.solution))
        if report['solution_loaded']:
            model.solutions.load_from(result)
        report['retained_max_scaled_constraint_violation'] = _constraint_violation(model.fs.root, scaled=True)
        report['retained_invalid_variables'] = [v.name for v in model.fs.root.component_data_objects(Var)
                                       if not _valid_guess(v)]
        report['success'] = (check_optimal_termination(result) and report['solution_loaded']
                             and report['retained_max_scaled_constraint_violation'] is not None
                             and report['retained_max_scaled_constraint_violation'] <= 1e-6
                             and not report['retained_invalid_variables'])
    except Exception as error:
        report.update(success=False, error=f'{type(error).__name__}: {error}')
    (HERE / 'attempt_rank_deficient_solve_result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['success'] else 1)
