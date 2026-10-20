"""Build and print a model structure without solving it."""

import argparse

from . import Library, build_model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", help="Root model ID")
    parser.add_argument("implementation", help="Explicit recursive implementation JSON")
    parser.add_argument("--library", help="Directory containing model JSON files")
    args = parser.parse_args()
    model = build_model(args.model, args.implementation, library=Library(args.library))
    model.pprint()


if __name__ == "__main__":
    main()
