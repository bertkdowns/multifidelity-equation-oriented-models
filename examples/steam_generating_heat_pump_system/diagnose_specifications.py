"""Relax the saved plant specifications on a clone and report joint adjustments.

Optional --vapor-enthalpy-scale replaces the pathological automatic equation
scale for one controlled experiment; it changes no physical equation.
"""
import argparse
import json
from pathlib import Path

from idaes.core.solvers import get_solver
from idaes.core.util.scaling import get_scaling_factor, set_scaling_factor
from pyomo.environ import Constraint, value, units
from pyomo.opt import check_optimal_termination
from multifidelity.model_language import (
    InformationDocument, SpecificationDocument, initialize_model, relax_specifications, get_variable,
)
from multifidelity.model_language.scaling import export_scaling
from attempt_solve import build_attempt

HERE = Path(__file__).resolve().parent


def physical_residuals(model):
    rows = []
    for c in model.component_data_objects(Constraint, active=True):
        body = value(c.body)
        violation = max(0, value(c.lower)-body if c.has_lb() else 0,
                        body-value(c.upper) if c.has_ub() else 0)
        rows.append(dict(name=c.name, violation=violation,
                         unit=str(units.get_units(c.body)),
                         scaled_violation=violation*get_scaling_factor(c, default=1)))
    # Different units cannot be compared physically; retain the unit on each row.
    return sorted(rows, key=lambda r: -r['violation'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vapor-enthalpy-scale', type=float)
    args = parser.parse_args()
    if args.vapor_enthalpy_scale is not None and not 0 < args.vapor_enthalpy_scale < float('inf'):
        parser.error('Equation scale must be finite and positive')
    m = build_attempt()
    information = InformationDocument.load_json(HERE/'attempt_information.json')
    specification = SpecificationDocument.load_json(HERE/'attempt_specification.json')
    initialization = initialize_model(m, information=information, specification=specification)
    if any(s.status != 'initialized' for s in initialization.stages[:-1]):
        raise RuntimeError('A component failed to initialize')
    relaxed = relax_specifications(m, specification, information)
    overrides = []
    if args.vapor_enthalpy_scale is not None:
        c = (relaxed.model.fs.root.relationship.models.flash_tank.relationship.models
             .vapor_mixture.relationship.slices[0.0].provider.enthalpy_equation)
        overrides.append(dict(name=c.name, original=get_scaling_factor(c),
                              replacement=args.vapor_enthalpy_scale))
        set_scaling_factor(c, args.vapor_enthalpy_scale)
    export_scaling(relaxed.model)
    solver = get_solver('ipopt', options={
        'max_iter':1000, 'tol':1e-8, 'max_cpu_time':90,
        'nlp_scaling_method':'user-scaling', 'linear_system_scaling':'none',
    })
    result = solver.solve(relaxed.model, tee=True, load_solutions=False)
    report = dict(termination=str(result.solver.termination_condition),
                  message=str(result.solver.message),
                  solution_returned=bool(len(result.solution)),
                  optimal=check_optimal_termination(result),
                  equation_scale_overrides=overrides,
                  weights='All selected records have weight 1')
    if len(result.solution):
        relaxed.model.solutions.load_from(result)
        report['deviations'] = relaxed.deviations()
        report['operating_values'] = {
            path: {str(index): dict(value=v.value, unit=str(units.get_units(v)))
                   for index, v in get_variable(relaxed.model, path).items()}
            for path in ['steam_outlet.flow', 'steam_outlet.enthalpy',
                         'sghp.source_inlet.flow', 'phnix.sink_inlet.flow',
                         'sghp.performance.cop', 'sghp.performance.electrical_power',
                         'phnix.performance.electrical_power']}
        flows = [dict(path=path, index=index, value=v.value)
                 for path, family in relaxed.model._model_language_variables.items()
                 if path.endswith('.flow') for index,v in family.items()]
        report['largest_flow_magnitudes'] = sorted(flows,key=lambda r:-abs(r['value']))[:10]

        residuals = physical_residuals(relaxed.model)
        report['largest_raw_residuals'] = residuals[:25]
        report['largest_scaled_residuals'] = sorted(residuals,key=lambda r:-r['scaled_violation'])[:25]
        report['max_scaled_violation'] = max(r['scaled_violation'] for r in residuals)
    name = 'specification_relaxation_corrected_scale' if overrides else 'specification_relaxation'
    (HERE/f'{name}_result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    raise SystemExit(0 if report['optimal'] else 1)
