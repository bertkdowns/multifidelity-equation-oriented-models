"""Bundle saved SGHP results and information without rebuilding or solving.

Defaults to the aggregate case. For the cycle case:
    .venv/bin/python examples/steam_generating_heat_pump_system/export_workspace.py \
        --results cycle_results.json --information cycle_attempt_information.json \
        --output cycle_workspace.json
Relative paths are resolved against this example directory.
"""

import argparse
from pathlib import Path

from multifidelity.model_language import WorkspaceDocument

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, default=Path('results.json'))
    parser.add_argument('--information', type=Path, default=Path('attempt_information.json'))
    parser.add_argument('--output', type=Path, default=Path('workspace.json'))
    args = parser.parse_args()
    workspace = WorkspaceDocument.from_results(HERE / args.results, HERE / args.information)
    output = HERE / args.output
    workspace.write_json(output)
    print(f'{output}: {workspace.results.solve.status}, {len(workspace.information.records)} records')


if __name__ == '__main__':
    main()
