"""Compare aggregate/aggregate with the saved fixed-power SGHP cycle case."""
import json
from pathlib import Path

from idaes.core.solvers import get_solver
from idaes.core.util.model_statistics import degrees_of_freedom
from multifidelity.model_language import (
    ResourceDocument, ParameterDocument, apply_parameters,
    pair_parameters, get_variable, export_results, WorkspaceDocument,
)
from multifidelity.model_language.scaling import apply_scaling, scaled_jacobian, export_scaling, rank_inputs
from multifidelity.model_language.selection import _partition
from build import build
from saved_state_guesses import seed_snapshot, refresh_properties
from diagnose_parameters import physical_residuals

HERE = Path(__file__).resolve().parent

if __name__ == '__main__':
    cycle = json.loads((HERE / 'cycle_results.json').read_text())
    cycle_values = {r['variable_path']: r['entries'][0]['value'] for r in cycle['variables']}
    base_info = ResourceDocument.load_json(HERE / 'attempt_resources.json')
    cycle_info = ResourceDocument.load_json(HERE / 'cycle_attempt_resources.json')
    power = cycle_info.get('attempt_sghp_operating_power')
    base_spec = ParameterDocument.load_json(HERE / 'attempt_parameters.json')
    reports = []
    for label, cop in [('cop4', 4.0), ('matched_cop', cycle_values['sghp.performance.cop']),
                       ('cycle_point', cycle_values['sghp.performance.cop'])]:
        model = build('aggregate', 'aggregate')
        records = [r.model_copy(update={'value': cop}) if r.tag == 'attempt_sghp_operating_cop' else r
                   for r in base_info.records]
        resources = ResourceDocument(root=(*records, power))
        tags = [i for i in base_spec.parameters if i != 'attempt_makeup_mass_flow'] + [power.tag]
        pairing_error = None
        try:
            parameters = pair_parameters(model, ParameterDocument(parameters=tags), resources)
        except ValueError as error:
            pairing_error = str(error)
            # Diagnostic only: apply the admissible partial parameters, then
            # impose the rejected power fixation explicitly to inspect its DM
            # partition and equations. This is not an accepted parameters.
            parameters = pair_parameters(model, ParameterDocument(
                parameters=[i for i in tags if i != power.tag]), resources)
        prefix = f'aggregate_power_{label}'
        (HERE / f'{prefix}_resources.json').write_text(resources.model_dump_json(indent=2)+'\n')
        (HERE / f'{prefix}_parameters.json').write_text(parameters.model_dump_json(indent=2)+'\n')
        apply_parameters(model, parameters, resources)
        if pairing_error is not None:
            get_variable(model, power.variable_path)[0].fix(power.value * 1000)
        seed_snapshot(model, HERE / 'cycle_results.json')
        if label == 'cycle_point':
            # Complete the extra aggregate-only guesses from the cycle's water
            # ports. This checks whether the cycle solution is itself feasible
            # in the aggregate equations, without adding a heat-allocation fix.
            for endpoint in ['inlet', 'outlet']:
                for field in ['flow', 'pressure', 'enthalpy']:
                    get_variable(model, f'sghp.warm_water_heater.{endpoint}.{field}')[0].set_value(
                        cycle_values[f'sghp.warm_{endpoint}.{field}'])
            for path, number in {
                'sghp.warm_water_heater.parameters.heat_duty': cycle_values['sghp.performance.warm_water_duty'],
                'sghp.cop_model.performance.cop': cop,
                'sghp.power_model.parameters.electrical_power': power.value * 1000,
                'sghp.power_model.performance.electrical_power': power.value * 1000,
            }.items():
                get_variable(model, path)[0].set_value(number)
        refresh_properties(model)
        apply_scaling(model); scaled_jacobian(model); export_scaling(model)
        vp, cp = _partition(model)
        report = dict(case=label, cop=cop, degrees_of_freedom=degrees_of_freedom(model),
                      structural_unmatched_variables=len(vp.unmatched),
                      structural_unmatched_constraints=len(cp.unmatched),
                      starting_snapshot='cycle_results.json',
                      accepted_parameters=pairing_error is None, pairing_error=pairing_error,
                      underconstrained_variables=len(vp.underconstrained),
                      overconstrained_constraints=len(cp.overconstrained))
        solver = get_solver('ipopt', options={
            'max_iter': 500, 'tol': 1e-8, 'max_cpu_time': 60,
            'nlp_scaling_method': 'user-scaling', 'linear_system_scaling': 'none',
        })
        result = solver.solve(model, tee=True, load_solutions=False)
        report['termination'] = str(result.solver.termination_condition)
        if len(result.solution):
            model.solutions.load_from(result)
            residuals = physical_residuals(model)
            report['max_scaled_violation'] = float(max(r['scaled_violation'] for r in residuals))
            report['largest_scaled_residuals'] = sorted(residuals, key=lambda r: -r['scaled_violation'])[:10]
            report['values'] = {
                path: dict(aggregate=get_variable(model, path)[0].value,
                           cycle=cycle_values.get(path))
                for path in ['steam_outlet.flow', 'makeup_state.state.flow',
                             'sghp.performance.electrical_power', 'sghp.performance.cop',
                             'sghp.performance.cooling_duty', 'sghp.performance.heating_duty',
                             'sghp.performance.hot_water_duty', 'sghp.performance.warm_water_duty',
                             'sghp.source_inlet.flow', 'sghp.hot_outlet.enthalpy',
                             'sghp.warm_outlet.enthalpy', 'sghp.source_outlet.enthalpy']}
        solved = report['termination'] == 'optimal' and report.get('max_scaled_violation', 1) < 1e-6
        report['solver_converged'] = bool(solved)
        _, report['jacobian'] = rank_inputs(model, [], 0)
        report['jacobian'].pop('candidates', None)
        report['solved'] = bool(solved and pairing_error is None and report['jacobian']['numerical_rank'] == report['jacobian']['columns'])
        snapshot = export_results(model, status='optimal' if report['solved'] else 'feasible' if solved else 'failed', solver='ipopt',
                       termination_condition=report['termination'], parameters=parameters if pairing_error is None else None,
                       message='Diagnostic only: rejected parameters pattern; compatible COP leaves heat allocation undetermined. Cycle snapshot used only as starting values.' if pairing_error else 'Aggregate comparison.')
        snapshot.write_json(HERE / f'{prefix}_results.json')
        WorkspaceDocument.from_results(snapshot, resources).write_json(HERE / f'{prefix}_workspace.json')
        (HERE / f'{prefix}_report.json').write_text(json.dumps(report, indent=2)+'\n')
        reports.append(report)
    (HERE / 'aggregate_power_comparison.json').write_text(json.dumps(reports, indent=2)+'\n')
    print(json.dumps(reports, indent=2))
