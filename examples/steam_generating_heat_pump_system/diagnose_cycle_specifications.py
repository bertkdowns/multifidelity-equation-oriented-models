"""Slack diagnostic for the detailed SGHP plant; failed iterates are not rankings."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
from idaes.core.solvers import get_solver
from pyomo.opt import check_optimal_termination
from multifidelity.model_language import (
    InformationDocument, SpecificationDocument, apply_specification,
    initialize_model, relax_specifications, get_variable, export_results, WorkspaceDocument,
    InformationRecord,
)
from multifidelity.model_language.scaling import scaled_jacobian, export_scaling
from build import build
from diagnose_specifications import physical_residuals

HERE = Path(__file__).resolve().parent

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-guesses', action='store_true')
    parser.add_argument('--coherent-guesses', action='store_true')
    args = parser.parse_args()
    name = 'cycle_specification_relaxation_reference' if args.reference_guesses else 'cycle_specification_relaxation'
    if args.coherent_guesses:
        args.reference_guesses = True
        name = 'cycle_specification_relaxation_coherent'
    model = build('cycle', 'aggregate')
    information = InformationDocument.load_json(HERE / 'cycle_flow_target_information.json')
    base_information = information
    specification = SpecificationDocument.load_json(HERE / 'cycle_flow_target_specification.json')
    if args.reference_guesses:
        capture = json.loads((HERE / 'ahuora_reference.json').read_text())
        objects = {o['id']: o for o in capture['objects']}
        def state(stream):
            props = {p['key']: p['values'][0]['value'] for p in objects[stream]['properties'] if p['values']}
            return {'flow': props['flow_mass'], 'pressure': props['pressure'] * 1000,
                    'enthalpy': props['enth_mass'] * 1000}
        ports = {
            'compressor.inlet': 1671821, 'compressor.outlet': 1671832,
            'condenser.hot_inlet': 1671832, 'condenser.hot_outlet': 1671805,
            'subcooler.hot_inlet': 1671805, 'subcooler.hot_outlet': 1671809,
            'ihx.hot_inlet': 1671809, 'ihx.hot_outlet': 1671820,
            'ihx.cold_inlet': 1671814, 'ihx.cold_outlet': 1671821,
            'expansion_valve.inlet': 1671820, 'expansion_valve.outlet': 1671823,
            'evaporator.cold_inlet': 1671823, 'evaporator.cold_outlet': 1671814,
            'refrigerant_mass_recycle.inlet': 1671821,
            'refrigerant_mass_recycle.outlet': 1671821,
        }
        guesses = {}
        for port, stream in ports.items():
            component, endpoint = port.split('.')
            prefixes = [f'sghp.{port}']
            prefixes += [f'sghp.{component}.{endpoint}_state.state',
                         f'sghp.{component}.{endpoint}_state.fluid.state']
            for prefix in prefixes:
                for field, number in state(stream).items():
                    path = prefix + '.' + field
                    if path in model._model_language_variables:
                        guesses[path] = number
        guesses['sghp.refrigerant_mass_recycle.flow_definition.flow'] = state(1671821)['flow']
        guesses['sghp.expansion_valve.parameters.pressure_drop'] = 2011686.3921285754
        records = [InformationRecord(id=f'cycle_guess_{i}', tag='captured_reference_starting_guess',
                                     information_type='assumption', variable_path=path, value=number,
                                     unit='kg/s' if path.endswith('.flow') else 'Pa' if path.endswith(('.pressure', '.pressure_drop')) else 'J/kg',
                                     trust_rank=1)
                   for i, (path, number) in enumerate(guesses.items())]
        information = InformationDocument(root=(*information.records, *records))
    apply_specification(model, specification, information)
    initialized = initialize_model(model, information=base_information if args.coherent_guesses else information,
                                   specification=specification)
    if args.coherent_guesses:
        from saved_state_guesses import seed_snapshot, refresh_properties
        from multifidelity.model_language import apply_starting_values
        # Diagnostic-only warm start: solved shared water states, captured butane
        # states, then evaluate native property definitions at those PH values.
        seed_snapshot(model, HERE / 'results.json')
        apply_starting_values(model, information, specification=specification)
        refresh_properties(model)

    relaxed = relax_specifications(model, specification, information)
    scaled_jacobian(relaxed.model)  # Recompute whole-plant equation scales after relaxation.
    export_scaling(relaxed.model)
    result = get_solver('ipopt', options={
        'max_iter': 1500, 'tol': 1e-8, 'max_cpu_time': 90,
        'nlp_scaling_method': 'user-scaling', 'linear_system_scaling': 'none',
    }).solve(relaxed.model, tee=True, load_solutions=False)
    report = dict(implementation='cycle_aggregate', initialization=asdict(initialized),
                  termination=str(result.solver.termination_condition),
                  optimal=check_optimal_termination(result),
                  weights='Variable scales; weight 1 for each selected specification')
    if len(result.solution):
        relaxed.model.solutions.load_from(result)
        report['deviations'] = relaxed.deviations()
        residuals = physical_residuals(relaxed.model)
        report['max_scaled_violation'] = max(r['scaled_violation'] for r in residuals)
        report['largest_scaled_residuals'] = sorted(residuals, key=lambda r: -r['scaled_violation'])[:20]
        report['largest_raw_residuals'] = residuals[:20]
        report['operating_values'] = {
            path: {str(i): v.value for i, v in get_variable(relaxed.model, path).items()}
            for path in ['steam_outlet.flow', 'sghp.performance.cop',
                         'sghp.performance.electrical_power', 'sghp.performance.hot_water_duty',
                         'sghp.performance.warm_water_duty', 'sghp.source_inlet.flow',
                         'sghp.compressor.inlet.pressure', 'sghp.compressor.outlet.pressure']}
    report['usable_ranking'] = bool(report['optimal'] and report.get('max_scaled_violation', 1) < 1e-6)
    (HERE / f'{name}_result.json').write_text(json.dumps(report, indent=2) + '\n')
    snapshot = export_results(relaxed.model, status='optimal' if report['usable_ranking'] else 'failed',
                   solver='ipopt', termination_condition=report['termination'],
                   message='Specification-relaxation diagnostic: selected specifications are soft.',
                   specification=specification)
    snapshot.write_json(HERE / f'{name}_results.json')
    WorkspaceDocument.from_results(snapshot, information).write_json(HERE / f'{name}_workspace.json')
    if report['usable_ranking'] and args.coherent_guesses:
        checks = []
        for entry in relaxed.entries:
            if entry['variable_path'] != 'makeup_state.state.flow':
                entry['variable'].fix(entry['target'])
        for label in ['only_makeup_free', 'all_original_specifications_fixed']:
            if label == 'all_original_specifications_fixed':
                for entry in relaxed.entries:
                    entry['variable'].fix(entry['target'])
            scaled_jacobian(relaxed.model)
            export_scaling(relaxed.model)
            check = get_solver('ipopt', options={
                'max_iter': 500, 'tol': 1e-8, 'max_cpu_time': 60,
                'nlp_scaling_method': 'user-scaling', 'linear_system_scaling': 'none',
            }).solve(relaxed.model, tee=True, load_solutions=False)
            row = dict(case=label, termination=str(check.solver.termination_condition),
                       optimal=bool(check_optimal_termination(check)))
            if len(check.solution):
                relaxed.model.solutions.load_from(check)
                residuals = physical_residuals(relaxed.model)
                row['max_scaled_violation'] = float(max(r['scaled_violation'] for r in residuals))
                row['largest_scaled_residuals'] = sorted(residuals, key=lambda r: -r['scaled_violation'])[:10]
                row['deviations'] = relaxed.deviations()
                row['steam_kg_h'] = float(get_variable(relaxed.model, 'steam_outlet.flow')[0].value * 3600)
                row['cop'] = float(get_variable(relaxed.model, 'sghp.performance.cop')[0].value)
            checks.append(row)
        (HERE / 'cycle_relaxation_verification.json').write_text(json.dumps(checks, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'initialization'}, indent=2))
    raise SystemExit(0 if report['usable_ranking'] else 1)
