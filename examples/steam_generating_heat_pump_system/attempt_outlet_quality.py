"""Solve the aggregate plant with prescribed flash outlet compositions.

Try the full operating specification directly if a local initialization stage
fails. A successful bottom-up root solve is retained without solving it twice.
"""
import json

from idaes.core.solvers import get_solver
from pyomo.environ import units
from multifidelity.model_language import (
    initialize_model, InformationDocument, SpecificationDocument, get_variable,
)
from multifidelity.model_language.scaling import rank_inputs, export_scaling
from attempt_solve import build_attempt, HERE
from diagnose_specifications import physical_residuals


if __name__ == '__main__':
    model = build_attempt()
    initialization = initialize_model(
        model,
        information=InformationDocument.load_json(HERE/'attempt_information.json'),
        specification=SpecificationDocument.load_json(HERE/'attempt_specification.json'),
    )
    _, diagnostic = rank_inputs(model.fs.root, [], 0)
    report = dict(initialization_stop=initialization.failed_model,
                  initialization_status=initialization.stages[-1].status,
                  root_rank=diagnostic,
                  topology='Explicit source_mass_recycle; all physical equations active')
    available = initialization.success
    if initialization.success:
        report.update(termination=initialization.stages[-1].solver_termination,
                      message='Bottom-up initializer solved the complete plant')
    else:
        export_scaling(model)
        solver = get_solver('ipopt', options={
            'max_iter':1000, 'max_cpu_time':90, 'tol':1e-8,
            'nlp_scaling_method':'user-scaling', 'linear_system_scaling':'none',
        })
        result = solver.solve(model, tee=True, load_solutions=False)
        report.update(termination=str(result.solver.termination_condition),
                      message=str(result.solver.message))
        available = bool(len(result.solution))
        if available:
            model.solutions.load_from(result)
    report['solution_returned'] = available
    if available:
        paths = [
            'flash_tank.liquid_properties.vapor_fraction',
            'flash_tank.vapor_properties.vapor_fraction',
            'flash_tank.parameters.liquid_to_liquid', 'flash_tank.parameters.vapor_to_liquid',
            'steam_outlet.flow', 'sghp.source_inlet.flow',
            'source_mass_recycle.inlet.flow', 'source_mass_recycle.outlet.flow',
            'source_mass_recycle.flow_definition.flow',
            'sghp.performance.cop', 'sghp.performance.electrical_power',
            'sghp.hot_inlet_state.properties.temperature', 'sghp.performance.warm_water_duty',
            'cooling_exchanger.hot_inlet_state.properties.temperature',
            'cooling_exchanger.hot_inlet_state.properties.vapor_fraction',
        ]
        report['operating_values'] = {
            path: {str(i): dict(value=v.value, unit=str(units.get_units(v)), fixed=v.fixed)
                   for i,v in get_variable(model,path).items()} for path in paths}
        rows = physical_residuals(model)
        report['largest_raw_residuals'] = rows[:10]
        report['largest_scaled_residuals'] = sorted(rows,key=lambda row:-row['scaled_violation'])[:10]
    (HERE/'attempt_outlet_quality_result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
