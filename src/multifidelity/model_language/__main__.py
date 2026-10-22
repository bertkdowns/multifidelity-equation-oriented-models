"""Inspect required inputs or build a model structure without solving it."""

import argparse

from . import Library, build_model, print_required_inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", help="Root model ID")
    parser.add_argument("implementation", help="Explicit recursive implementation JSON")
    parser.add_argument("--library", help="Directory containing model JSON files")
    parser.add_argument(
        "--required-inputs",
        action="store_true",
        help="List required variable paths and units instead of building Pyomo",
    )
    args = parser.parse_args()
    if args.required_inputs:
        print_required_inputs(
            args.model, args.implementation, library=Library(args.library)
        )
        return
    model = build_model(args.model, args.implementation, library=Library(args.library))
    model.pprint()


if __name__ == "__main__":
    main()
