"""Try detailed SGHP / aggregate PHNIX, preserving shared plant parameters."""

import argparse
import math
from dataclasses import asdict
import json
from pathlib import Path

from idaes.core.solvers import get_solver
from idaes.core.util.model_statistics import degrees_of_freedom
from multifidelity.model_language import (
    ResourceDocument, ParameterDocument, apply_parameters,
    initialize_model, export_results, WorkspaceDocument, pair_parameters,
)
from build import build

HERE = Path(__file__).resolve().parent

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--power-kw', type=float, default=15.20,
                        help='SGHP electrical power in kW (default: 15.20, working demonstration).')
    args = parser.parse_args()
    if args.power_kw is not None and (not math.isfinite(args.power_kw) or args.power_kw <= 0):
        parser.error('--power-kw must be finite and positive')
    model = build('cycle', 'aggregate')
    resources = ResourceDocument.load_json(HERE / 'attempt_resources.json')
    observations = ResourceDocument.load_json(HERE / 'reference_observations.json')
    pressure_rise = observations.get('reference_sghp_compressor_parameters_pressure_rise')
    # A frozen captured output, explicitly used as an operating assumption here.
    power = observations.get('reference_sghp_performance_electrical_power')
    if args.power_kw is not None:
        power = power.model_copy(update={
            'tag': 'attempt_sghp_operating_power',
            'value': args.power_kw, 'unit': 'kW', 'trust_rank': 8,
        })
    resources = ResourceDocument(root=(*resources.records, pressure_rise, power))
    resources_path = HERE / 'cycle_attempt_resources.json'
    resources_path.write_text(resources.model_dump_json(indent=2) + '\n')
    base = ParameterDocument.load_json(HERE / 'attempt_parameters.json')
    # COP is predicted by the cycle; replace the aggregate-only COP parameter
    # with captured exchanger conductances and compressor efficiency.
    tags = [i for i in base.parameters if i not in {'attempt_sghp_operating_cop', 'attempt_makeup_mass_flow'}]
    tags += [f'config_sghp_{name}_parameters_conductance'
            for name in ('condenser', 'evaporator', 'subcooler', 'ihx')]
    tags += ['config_sghp_compressor_parameters_efficiency',
            'reference_sghp_compressor_parameters_pressure_rise',
            power.tag]
    parameters = pair_parameters(model, ParameterDocument(parameters=tags), resources)
    (HERE / 'cycle_attempt_parameters.json').write_text(parameters.model_dump_json(indent=2) + '\n')
    apply_parameters(model, parameters, resources)
    print(f'Degrees of freedom: {degrees_of_freedom(model)}', flush=True)
    result = initialize_model(
        model, resources=resources, parameters=parameters,
        solver=get_solver('ipopt', options={
            'max_iter': 500, 'tol': 1e-8, 'max_cpu_time': 60,
            'linear_system_scaling': 'none',
        }),
    )
    report = {'model_document': 'cycle_aggregate', 'degrees_of_freedom': degrees_of_freedom(model), **asdict(result)}
    (HERE / 'cycle_attempt_result.json').write_text(json.dumps(report, indent=2) + '\n')
    if not result.success:
        from multifidelity.model_language.hierarchical_initialization import _constraint_violation
        from saved_state_guesses import seed_snapshot, refresh_properties
        from multifidelity.model_language.scaling import scaled_jacobian, export_scaling
        seed_path = HERE / 'cycle_parameters_relaxation_coherent_results.json'
        seed_snapshot(model, seed_path)
        refresh_properties(model)
        scaled_jacobian(model)
        export_scaling(model)
        report['starting_snapshot'] = seed_path.name
        solver = get_solver('ipopt', options={
            'max_iter': 1000, 'tol': 1e-8, 'max_cpu_time': 60,
            'nlp_scaling_method': 'user-scaling',
            'linear_system_scaling': 'none',
        })
        try:
            direct = solver.solve(model, tee=True, load_solutions=False)
            report['direct_solver_termination'] = str(direct.solver.termination_condition)
            if len(direct.solution):
                model.solutions.load_from(direct)
                report['direct_max_scaled_violation'] = _constraint_violation(model, scaled=True)
                report['direct_max_physical_violation'] = _constraint_violation(model, scaled=False)
        except Exception as error:
            report['direct_error'] = str(error)

    from diagnose_parameters import physical_residuals
    from multifidelity.model_language import get_variable
    report['operating_values'] = {
        path: get_variable(model, path)[0].value for path in [
            'steam_outlet.flow', 'makeup_state.state.flow',
            'sghp.performance.electrical_power', 'sghp.performance.cop',
            'sghp.performance.hot_water_duty', 'sghp.performance.warm_water_duty',
            'sghp.source_inlet.flow', 'phnix.performance.electrical_power']}
    report['largest_physical_residuals'] = physical_residuals(model)[:10]
    solved = result.success or (report.get('direct_solver_termination') == 'optimal'
                                and report.get('direct_max_scaled_violation', 1) < 1e-6)
    report['solved'] = bool(solved)
    (HERE / 'cycle_attempt_result.json').write_text(json.dumps(report, indent=2) + '\n')
    snapshot = export_results(model, status='optimal' if solved else 'failed',
                   solver='ipopt', termination_condition=report.get('direct_solver_termination', result.stages[-1].solver_termination),
                   message=None if solved else result.stages[-1].error, parameters=parameters,
                   )
    snapshot.write_json(HERE / 'cycle_results.json')
    WorkspaceDocument.from_results(snapshot, resources).write_json(HERE / 'cycle_workspace.json')
    print(json.dumps(report, indent=2), flush=True)
    raise SystemExit(0 if solved else 1)
