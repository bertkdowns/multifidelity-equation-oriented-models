"""Bundle saved SGHP results and resources without rebuilding or solving.

Defaults to the aggregate case. For the cycle case:
    .venv/bin/python examples/steam_generating_heat_pump_system/export_workspace.py \
        --results cycle_results.json --resources cycle_attempt_resources.json \
        --output cycle_workspace.json
Relative paths are resolved against this example directory.
"""

import argparse
from pathlib import Path

from multifidelity.model_language import WorkspaceCatalog

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, default=Path('results.json'))
    parser.add_argument('--resources', type=Path, default=Path('attempt_resources.json'))
    parser.add_argument('--output', type=Path, default=Path('workspace.json'))
    args = parser.parse_args()
    workspace = WorkspaceCatalog.from_results(HERE / args.results, HERE / args.resources)
    output = HERE / args.output
    workspace.write_json(output)
    print(f'{output}: {workspace.results.solve.status}, {len(workspace.resources.records)} records')


if __name__ == '__main__':
    main()
