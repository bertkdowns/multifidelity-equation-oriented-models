"""Attempt the complete aggregate plant with explicit specifications and no guesses.

Run from the repository root with:
    .venv/bin/python examples/steam_generating_heat_pump_system/attempt_solve.py
Add --diagnostic to stop on the first invalid equation evaluation.
"""

import argparse
from pathlib import Path

from idaes.core.solvers import get_solver
from idaes.core.util.model_statistics import degrees_of_freedom
from multifidelity.model_language import (
    InformationDocument, Library, SpecificationDocument, apply_specification,
    build_model, register_standard_providers,
)

HERE = Path(__file__).resolve().parent


def build_attempt():
    library = Library()
    register_standard_providers(library)
    model = build_model('steam_generating_heat_pump_system',
                        HERE / 'aggregate_aggregate.json', library=library)
    apply_specification(model,
                        SpecificationDocument.load_json(HERE / 'attempt_specification.json'),
                        InformationDocument.load_json(HERE / 'attempt_information.json'))
    return model


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--diagnostic', action='store_true')
    args = parser.parse_args()
    model = build_attempt()
    print(f'Degrees of freedom: {degrees_of_freedom(model)}', flush=True)
    options = {'max_iter': 500, 'tol': 1e-8}
    if args.diagnostic:
        options['halt_on_ampl_error'] = 'yes'
    # Deliberately no numerical initialization or calls to replay helpers.
    result = get_solver('ipopt', options=options).solve(
        model, tee=True, load_solutions=False, symbolic_solver_labels=True,
    )
    print(result.solver)
    if str(result.solver.termination_condition) != "optimal":
        raise SystemExit(1)
