"""Try bottom-up initialisation under the saved aggregate-plant specification.

Run from the repository root:
    .venv/bin/python examples/steam_generating_heat_pump_system/attempt_bottom_up.py
"""

from dataclasses import asdict
import json
from pathlib import Path

from idaes.core.solvers import get_solver
from multifidelity.model_language import (
    InformationDocument, SpecificationDocument, initialize_model,
)
from attempt_solve import build_attempt

HERE = Path(__file__).resolve().parent


if __name__ == '__main__':
    model = build_attempt()
    result = initialize_model(
        model,
        information=InformationDocument.load_json(HERE / 'attempt_information.json'),
        specification=SpecificationDocument.load_json(HERE / 'attempt_specification.json'),
        solver=get_solver('ipopt', options={
            'max_iter': 500, 'tol': 1e-8, 'max_cpu_time': 60,
        }),
    )
    report = {
        'implementation': 'aggregate_aggregate',
        'specification': 'attempt_specification.json',
        'information': 'attempt_information.json',
        **asdict(result),
    }
    text = json.dumps(report, indent=2) + '\n'
    (HERE / 'attempt_bottom_up_result.json').write_text(text)
    print(text)
    raise SystemExit(0 if result.success else 1)
