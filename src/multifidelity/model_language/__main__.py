"""Inspect required inputs or build a model structure without solving it."""

import argparse

from . import BlockRegistry, build_model, print_required_inputs, register_standard_providers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("block", help="Root block ID")
    parser.add_argument("model_document", help="Model document with explicit recursive formulation choices")
    parser.add_argument("--registry", help="Directory containing block definitions")
    parser.add_argument(
        "--standard-providers",
        action="store_true",
        help="Register bundled Helmholtz, humid-air, and compressor-map symbolic providers",
    )
    parser.add_argument(
        "--required-inputs",
        action="store_true",
        help="List required variable paths and units instead of building Pyomo",
    )
    args = parser.parse_args()
    registry = BlockRegistry(args.registry)
    if args.required_inputs:
        print_required_inputs(args.block, args.model_document, registry=registry)
        return
    if args.standard_providers:
        register_standard_providers(registry)
    model = build_model(args.block, args.model_document, registry=registry)
    model.pprint()


if __name__ == "__main__":
    main()
