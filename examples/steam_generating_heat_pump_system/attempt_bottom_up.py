"""Try bottom-up initialisation under the saved aggregate-plant parameters.

Run from the repository root:
    .venv/bin/python examples/steam_generating_heat_pump_system/attempt_bottom_up.py
"""


from dataclasses import asdict
import json
from pathlib import Path

from idaes.core.solvers import get_solver
from multifidelity.model_language import (
    ResourceDocument, ParameterDocument, get_variable, initialize_model, export_results, WorkspaceDocument,
)
from attempt_solve import build_attempt

HERE = Path(__file__).resolve().parent


if __name__ == '__main__':
    model = build_attempt()
    result = initialize_model(
        model,
        resources=ResourceDocument.load_json(HERE / 'attempt_resources.json'),
        parameters=ParameterDocument.load_json(HERE / 'attempt_parameters.json'),
        solver=get_solver('ipopt', options={
            'max_iter': 500, 'tol': 1e-8, 'max_cpu_time': 60,
            'linear_system_scaling': 'none',
        }),
    )
    snapshot = export_results(
        model, status='optimal' if result.success else 'failed', solver='ipopt',
        termination_condition=result.stages[-1].solver_termination,
        message=result.stages[-1].error,
        parameters=HERE / 'attempt_parameters.json',
    )
    snapshot.write_json(HERE / 'results.json')
    WorkspaceDocument.from_results(snapshot, HERE / 'attempt_resources.json').write_json(HERE / 'workspace.json')
    report = {
        'model_document': 'aggregate_aggregate',
        'parameters': 'attempt_parameters.json',
        'resources': 'attempt_resources.json',
        **asdict(result),
    }
    from multifidelity.model_language.hierarchical_initialization import _constraint_violation
    report['full_model_max_scaled_violation'] = _constraint_violation(model, scaled=True)
    # On root success these are plant solution states; on failure they retain
    # successful child initialization values after parent rollback.
    initialized = {stage.model_path for stage in result.stages if stage.status == 'initialized'}
    report['initialized_water_states'] = {}
    for prefix in ['sghp.source_inlet_state', 'sghp.hot_inlet_state', 'sghp.warm_inlet_state']:
        if prefix in initialized:
            report['initialized_water_states'][prefix] = {
                field: get_variable(model, f'{prefix}.{field}')[model.fs.time.first()].value
                for field in ['state.flow', 'state.pressure', 'state.enthalpy',
                              'properties.temperature', 'properties.density']
            }
    report['initialized_water_states_units'] = {
        'state.flow': 'kg/s', 'state.pressure': 'Pa', 'state.enthalpy': 'J/kg',
        'properties.temperature': 'K', 'properties.density': 'kg/m**3',
    }
    text = json.dumps(report, indent=2) + '\n'
    (HERE / 'attempt_bottom_up_result.json').write_text(text)
    print(text)
    raise SystemExit(0 if result.success else 1)
