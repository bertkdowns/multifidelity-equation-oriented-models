"""Solve both SGHP fidelities with identical plant operating specifications.

PHNIX stays aggregate. SGHP power and warm-water duty are specified; COP,
steam/makeup flow and (for the cycle) compressor pressure rise are predictions.
"""
import json
from pathlib import Path

from idaes.core.solvers import get_solver
from idaes.core.util.model_statistics import degrees_of_freedom
from multifidelity.model_language import (
    InformationDocument, InformationRecord, SpecificationDocument,
    pair_specification, apply_specification, get_variable, export_results, WorkspaceDocument,
)
from multifidelity.model_language.scaling import apply_scaling, rank_inputs, scaled_jacobian, export_scaling
from multifidelity.model_language.selection import _partition
from build import build
from saved_state_guesses import seed_snapshot, refresh_properties
from diagnose_specifications import physical_residuals

HERE = Path(__file__).resolve().parent
CYCLE_EQUIPMENT = [f'config_sghp_{name}_parameters_conductance'
                   for name in ('condenser', 'evaporator', 'subcooler', 'ihx')]
CYCLE_EQUIPMENT += ['config_sghp_compressor_parameters_efficiency']


def common_case():
    """Freeze the reference duty explicitly; later results cannot change it."""
    information = InformationDocument.load_json(HERE / 'attempt_information.json')
    power = InformationRecord(
        id='common_sghp_power', tag='user_assumption.sghp_operating_power',
        information_type='assumption', variable_path='sghp.performance.electrical_power',
        value=15.20, unit='kW', trust_rank=8)
    warm = InformationRecord(
        id='common_sghp_warm_duty', tag='comparison.reference_cycle_warm_water_duty',
        information_type='assumption', variable_path='sghp.performance.warm_water_duty',
        value=25598.804912630734, unit='W', trust_rank=8)
    information = InformationDocument(root=(*information.records, power, warm))
    base = SpecificationDocument.load_json(HERE / 'attempt_specification.json')
    ids = [i for i in base.specifications if i not in {
        'attempt_makeup_mass_flow', 'attempt_sghp_operating_cop'}]
    return information, ids + [power.id, warm.id]


def run(sghp, information, common_ids):
    model = build(sghp, 'aggregate')
    ids = common_ids + (CYCLE_EQUIPMENT if sghp == 'cycle' else [])
    specification = pair_specification(model, SpecificationDocument(specifications=ids), information)
    apply_specification(model, specification, information)
    seed_snapshot(model, HERE / 'cycle_results.json')
    if sghp == 'aggregate':
        # Seed the aggregate-only heater/COP/power variables consistently with
        # the cycle snapshot. These values are guesses, not extra fixations.
        for endpoint in ['inlet', 'outlet']:
            for field in ['flow', 'pressure', 'enthalpy']:
                get_variable(model, f'sghp.warm_water_heater.{endpoint}.{field}')[0].set_value(
                    get_variable(model, f'sghp.warm_{endpoint}.{field}')[0].value)
        for target, source in {
            'sghp.warm_water_heater.parameters.heat_duty': 'sghp.performance.warm_water_duty',
            'sghp.cop_model.parameters.cop': 'sghp.performance.cop',
            'sghp.cop_model.performance.cop': 'sghp.performance.cop',
            'sghp.power_model.parameters.electrical_power': 'sghp.performance.electrical_power',
            'sghp.power_model.performance.electrical_power': 'sghp.performance.electrical_power',
        }.items():
            get_variable(model, target)[0].set_value(get_variable(model, source)[0].value)
    refresh_properties(model)
    apply_scaling(model); scaled_jacobian(model); export_scaling(model)
    vp, cp = _partition(model)
    report = dict(sghp=sghp, phnix='aggregate', degrees_of_freedom=degrees_of_freedom(model),
                  unmatched_variables=len(vp.unmatched), unmatched_constraints=len(cp.unmatched),
                  underconstrained_variables=len(vp.underconstrained),
                  overconstrained_constraints=len(cp.overconstrained),
                  common_specification_ids=common_ids,
                  equipment_specification_ids=CYCLE_EQUIPMENT if sghp == 'cycle' else [],
                  starting_snapshot='cycle_results.json')
    if any(report[k] for k in ['degrees_of_freedom', 'unmatched_variables', 'unmatched_constraints',
                              'underconstrained_variables', 'overconstrained_constraints']):
        raise RuntimeError(f'Unclosed specification: {report}')
    result = get_solver('ipopt', options={
        'max_iter': 500, 'tol': 1e-8, 'max_cpu_time': 60,
        'nlp_scaling_method': 'user-scaling', 'linear_system_scaling': 'none',
    }).solve(model, tee=True, load_solutions=False)
    report['termination'] = str(result.solver.termination_condition)
    if len(result.solution):
        model.solutions.load_from(result)
        residuals = physical_residuals(model)
        report['max_scaled_violation'] = float(max(r['scaled_violation'] for r in residuals))
        report['largest_physical_residuals'] = residuals[:10]
        _, report['jacobian'] = rank_inputs(model, [], 0)
        report['jacobian'].pop('candidates', None)
        paths = ['steam_outlet.flow', 'makeup_state.state.flow',
                 'sghp.performance.electrical_power', 'sghp.performance.cop',
                 'sghp.performance.heating_duty', 'sghp.performance.cooling_duty',
                 'sghp.performance.hot_water_duty', 'sghp.performance.warm_water_duty',
                 'sghp.source_inlet.flow', 'sghp.hot_outlet.enthalpy',
                 'sghp.warm_outlet.enthalpy', 'sghp.source_outlet.enthalpy',
                 'cooling_exchanger.hot_inlet_state.properties.vapor_fraction']
        if sghp == 'cycle':
            paths.append('sghp.compressor.parameters.pressure_rise')
        report['values'] = {p: get_variable(model, p)[0].value for p in paths}
    report['solved'] = bool(report['termination'] == 'optimal'
                            and report.get('max_scaled_violation', 1) < 1e-6
                            and report['jacobian']['numerical_rank'] == report['jacobian']['columns'])
    prefix = f'common_{sghp}_aggregate'
    (HERE / f'{prefix}_specification.json').write_text(specification.model_dump_json(indent=2)+'\n')
    (HERE / f'{prefix}_report.json').write_text(json.dumps(report, indent=2)+'\n')
    export_results(model, status='optimal' if report['solved'] else 'failed', solver='ipopt',
                   termination_condition=report['termination'], specification=specification,
                   message='Common fixed-power/fixed-warm-duty comparison.').write_json(HERE / f'{prefix}_results.json')
    WorkspaceDocument.from_results(HERE / f'{prefix}_results.json', information).write_json(
        HERE / f'{prefix}_workspace.json')
    return report


if __name__ == '__main__':
    information, common_ids = common_case()
    (HERE / 'common_operating_information.json').write_text(information.model_dump_json(indent=2)+'\n')
    reports = [run(sghp, information, common_ids) for sghp in ['aggregate', 'cycle']]
    values = reports[0].get('values', {})
    differences = {p: dict(aggregate=v, cycle=reports[1]['values'][p],
                           difference=v-reports[1]['values'][p])
                   for p,v in values.items() if p in reports[1].get('values', {})}
    comparison = dict(cases=reports, differences=differences,
                      note='Warm duty is calibrated from the cycle reference; matching that split is not an independent performance validation.')
    (HERE / 'common_fidelity_comparison.json').write_text(json.dumps(comparison, indent=2)+'\n')
    print(json.dumps(comparison, indent=2))
    raise SystemExit(0 if all(r['solved'] for r in reports) else 1)
