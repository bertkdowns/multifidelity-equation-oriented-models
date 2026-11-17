"""Construct the same SGHP plant with independently selected heat-pump detail."""

import argparse
import json
from pathlib import Path

from pyomo.environ import Constraint, Var
from pyomo.util.check_units import assert_units_consistent

from multifidelity.model_language import (
    ResourceDocument, apply_parameters, build_model, required_inputs,
    select_parameters, BlockRegistry, register_standard_providers, export_workspace,
)

HERE = Path(__file__).resolve().parent
MODEL = 'steam_generating_heat_pump_system'


def build(sghp='aggregate', phnix='aggregate'):
    model_document = HERE / f'{sghp}_{phnix}.json'
    registry = BlockRegistry()
    register_standard_providers(registry)
    model = build_model(MODEL, model_document, registry=registry)
    assert_units_consistent(model)
    return model


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sghp', choices=['aggregate', 'cycle'], default='aggregate')
    parser.add_argument('--phnix', choices=['aggregate', 'cycle'], default='aggregate')
    parser.add_argument('--apply-reference', action='store_true',
                        help='Select and apply applicable captured configuration; report missing resources.')
    args = parser.parse_args()
    model = build(args.sghp, args.phnix)
    inputs = required_inputs(MODEL, HERE / f'{args.sghp}_{args.phnix}.json')
    report = {
        'block': MODEL,
        'sghp': args.sghp,
        'phnix': args.phnix,
        'variables': sum(1 for _ in model.component_data_objects(Var)),
        'equations': sum(1 for _ in model.component_data_objects(Constraint)),
        'required_input_families': {path: variable.unit for path, variable in inputs.items()},
        'status': 'constructed; no operating values applied or numerical solve attempted',
    }
    if args.apply_reference:
        resources = ResourceDocument.load_json(HERE / 'resources.json')
        selection = select_parameters(
            model, resources,
            prediction_targets=['performance.electrical_power', 'steam_outlet.flow'],
        )
        apply_parameters(model, selection.parameters, resources)
        report['reference_parameters'] = {
            'complete': selection.complete,
            'remaining_deficiency': selection.remaining_deficiency,
            'selected_record_tags': list(selection.parameters.parameters),
            'replacements': selection.parameters.replacements,
            'pairing_error': selection.pairing_error,
            'decisions': selection.decisions,
        }
        report['status'] = 'reference configuration partially applied; no numerical solve attempted'
    workspace = HERE / f'{args.sghp}_{args.phnix}_workspace.json'
    export_workspace(model, HERE / 'resources.json', status='not_solved',
                     parameters=selection.parameters if args.apply_reference else None).write_json(workspace)
    report['workspace'] = str(workspace)
    print(json.dumps(report, indent=2))
