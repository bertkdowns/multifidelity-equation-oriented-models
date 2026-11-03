"""Replay the captured SGHP unit point using a COP calibrated at that same point.

This tests aggregate construction and value mapping, not predictive performance,
phase equilibrium, or consistency of the surrounding closed plant loops.
"""

import json
from pathlib import Path

from idaes.core.solvers import get_solver
from idaes.core.util.model_statistics import degrees_of_freedom
from pyomo.environ import Var, assert_optimal_termination, value

from multifidelity.model_language import (
    InformationDocument, SpecificationDocument, apply_specification,
    build_model, get_variable,
)

HERE = Path(__file__).resolve().parent


def replay(solver=None):
    implementation = json.loads((HERE / 'aggregate_aggregate.json').read_text())
    model = build_model('steam_generating_heat_pump_unit', implementation['submodels']['sghp'])
    information = InformationDocument.load_json(HERE / 'sghp_replay_information.json')
    specification = SpecificationDocument.load_json(HERE / 'sghp_replay_specification.json')
    apply_specification(model, specification, information)
    if degrees_of_freedom(model) != 0:
        raise RuntimeError('The captured SGHP unit replay must have zero degrees of freedom')
    # Numerical guesses only; none of the outlet reference values is fixed.
    for variable in model.component_data_objects(Var):
        if not variable.fixed:
            variable.set_value(1)
    for side in ['source', 'hot', 'warm']:
        for field in ['flow', 'pressure', 'enthalpy']:
            inlet = value(get_variable(model, f'{side}_inlet.{field}')[0])
            get_variable(model, f'{side}_outlet.{field}')[0].set_value(inlet)
    solver = solver if solver is not None else get_solver('ipopt')
    if not solver.available(False):
        raise RuntimeError('IPOPT is required for the SGHP unit replay')
    result = solver.solve(model)
    assert_optimal_termination(result)
    paths = [f'{side}_outlet.{field}' for side in ['source', 'hot', 'warm']
             for field in ['flow', 'pressure', 'enthalpy']]
    paths += [f'performance.{name}' for name in [
        'electrical_power', 'cop', 'heating_duty', 'cooling_duty',
    ]]
    outputs = {path: value(get_variable(model, path)[0]) for path in paths}
    return model, result, outputs


if __name__ == '__main__':
    _, result, outputs = replay()
    print(json.dumps({
        'purpose': 'same-point calibrated replay; not predictive validation',
        'termination_condition': str(result.solver.termination_condition),
        'outputs_in_declared_SI_units': outputs,
    }, indent=2))
