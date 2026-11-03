"""Construct the same SGHP plant with independently selected heat-pump detail."""

import argparse
import json
from pathlib import Path

from pyomo.environ import Constraint, Var
from pyomo.util.check_units import assert_units_consistent

from multifidelity.model_language import (
    InformationDocument, apply_specification, build_model, required_inputs,
    select_specification, Library, register_standard_providers,
)

HERE = Path(__file__).resolve().parent
MODEL = 'steam_generating_heat_pump_system'


def build(sghp='aggregate', phnix='aggregate'):
    implementation = HERE / f'{sghp}_{phnix}.json'
    library = Library()
    register_standard_providers(library)
    model = build_model(MODEL, implementation, library=library)
    assert_units_consistent(model)
    return model


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sghp', choices=['aggregate', 'cycle'], default='aggregate')
    parser.add_argument('--phnix', choices=['aggregate', 'cycle'], default='aggregate')
    parser.add_argument('--apply-reference', action='store_true',
                        help='Select and apply applicable captured configuration; report missing information.')
    args = parser.parse_args()
    model = build(args.sghp, args.phnix)
    inputs = required_inputs(MODEL, HERE / f'{args.sghp}_{args.phnix}.json')
    report = {
        'model': MODEL,
        'sghp': args.sghp,
        'phnix': args.phnix,
        'variables': sum(1 for _ in model.component_data_objects(Var)),
        'equations': sum(1 for _ in model.component_data_objects(Constraint)),
        'required_input_families': {path: variable.unit for path, variable in inputs.items()},
        'status': 'constructed; no operating values applied or numerical solve attempted',
    }
    if args.apply_reference:
        information = InformationDocument.load_json(HERE / 'information.json')
        selection = select_specification(
            model, information,
            prediction_targets=['performance.electrical_power', 'steam_outlet.flow'],
        )
        apply_specification(model, selection.specification, information)
        report['reference_specification'] = {
            'complete': selection.complete,
            'remaining_deficiency': selection.remaining_deficiency,
            'selected_record_ids': list(selection.specification.specifications),
            'decisions': selection.decisions,
        }
        report['status'] = 'reference configuration partially applied; no numerical solve attempted'
    print(json.dumps(report, indent=2))
