"""Derive required input specifications from explicit relationship selections."""

from pathlib import Path
from typing import TextIO
import sys

from .definitions import Variable
from .implementation import ImplementationDocument
from .indexing import derivative_variables
from .resolution import Library
from ._traversal import _walk_implementation


def _selected_occurrences(model_id, implementation, library):
    library = library or Library()
    occurrences = []

    def collect(occurrence, parent, alias):
        occurrences.append((
            occurrence.model, occurrence.relationship,
            occurrence.prefix, occurrence.supplied,
        ))

    _walk_implementation(library.resolve(model_id), implementation, collect)
    return occurrences


def required_inputs(
    model_id: str,
    implementation: ImplementationDocument | dict | str | Path,
    *,
    library: Library | None = None,
) -> dict[str, Variable]:
    """Return required input families, retaining dimensions, by root-relative path.

    No values, solver variables or equations are created. Results describe
    declaration coverage, not solvability or initial-state requirements.
    """
    required = {}
    for model, _, prefix, supplied in _selected_occurrences(model_id, implementation, library):
        for struct_id, struct in model.structs.items():
            if struct.direction == "input":
                for name, variable in struct.variables.items():
                    local = f"{struct_id}.{name}"
                    if local not in supplied:
                        required[prefix + local] = variable
    return dict(sorted(required.items()))


def required_initial_values(
    model_id: str,
    implementation: ImplementationDocument | dict | str | Path,
    *,
    library: Library | None = None,
) -> dict[str, Variable]:
    """Default dynamic initial specifications: the output of each derivative.

    A family with other indices needs a starting profile. This is the authoring
    convention, not proof that all specifications are independent in a DAE.
    """
    required = {}
    for model, relationship, prefix, _ in _selected_occurrences(model_id, implementation, library):
        for derivative in relationship.derivatives.values():
            state, rate = derivative_variables(model, derivative)
            required[prefix + derivative.determines] = (
                state if derivative.determines == derivative.state else rate
            )
    return dict(sorted(required.items()))


def print_required_inputs(
    model_id: str,
    implementation,
    *,
    library: Library | None = None,
    file: TextIO | None = None,
) -> None:
    """Print one required variable path and declared unit per line."""
    for path, variable in required_inputs(
        model_id, implementation, library=library
    ).items():
        print(
            f"{path} [{variable.unit}]", file=file if file is not None else sys.stdout
        )
