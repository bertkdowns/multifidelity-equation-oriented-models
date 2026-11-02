"""Inspect required inputs or build a model structure without solving it."""

import argparse

from . import Library, build_model, print_required_inputs, register_standard_providers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", help="Root model ID")
    parser.add_argument("implementation", help="Implementation document with explicit recursive relationship choices")
    parser.add_argument("--library", help="Directory containing model documents")
    parser.add_argument(
        "--standard-providers",
        action="store_true",
        help="Register bundled Helmholtz, humid-air, and compressor-map providers",
    )
    parser.add_argument(
        "--required-inputs",
        action="store_true",
        help="List required variable paths and units instead of building Pyomo",
    )
    args = parser.parse_args()
    library = Library(args.library)
    if args.required_inputs:
        print_required_inputs(args.model, args.implementation, library=library)
        return
    if args.standard_providers:
        register_standard_providers(library)
    model = build_model(args.model, args.implementation, library=library)
    model.pprint()


if __name__ == "__main__":
    main()
