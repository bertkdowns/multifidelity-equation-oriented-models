"""Derive required input parameters from explicit formulation selections."""

from pathlib import Path
from typing import TextIO
import sys

from .definitions import Variable
from .model_selection import ModelCatalog
from .indexing import derivative_variables
from .resolution import BlockLibrary
from ._traversal import _walk_model


def _selected_occurrences(block_id, model_catalog, library):
    library = library or BlockLibrary()
    occurrences = []

    def collect(occurrence, parent, alias):
        occurrences.append((
            occurrence.block, occurrence.formulation,
            occurrence.prefix, occurrence.supplied,
        ))

    _walk_model(library.resolve(block_id), model_catalog, collect)
    return occurrences


def required_inputs(
    block_id: str,
    model_catalog: ModelCatalog | dict | str | Path,
    *,
    library: BlockLibrary | None = None,
) -> dict[str, Variable]:
    """Return required input families, retaining dimensions, by root-relative path.

    No values, solver variables or equations are created. Results describe
    declaration coverage, not solvability or initial-state requirements.
    """
    required = {}
    for model, _, prefix, supplied in _selected_occurrences(block_id, model_catalog, library):
        for struct_id, struct in model.structs.items():
            if struct.direction == "input":
                for name, variable in struct.variables.items():
                    local = f"{struct_id}.{name}"
                    if local not in supplied:
                        required[prefix + local] = variable
    return dict(sorted(required.items()))


def required_initial_values(
    block_id: str,
    model_catalog: ModelCatalog | dict | str | Path,
    *,
    library: BlockLibrary | None = None,
) -> dict[str, Variable]:
    """Default dynamic initial parameters: the output of each derivative.

    A family with other indices needs a starting profile. This is the authoring
    convention, not proof that all parameters are independent in a DAE.
    """
    required = {}
    for model, formulation, prefix, _ in _selected_occurrences(block_id, model_catalog, library):
        for derivative in formulation.derivatives.values():
            state, rate = derivative_variables(model, derivative)
            required[prefix + derivative.determines] = (
                state if derivative.determines == derivative.state else rate
            )
    return dict(sorted(required.items()))


def print_required_inputs(
    block_id: str,
    model_catalog,
    *,
    library: BlockLibrary | None = None,
    file: TextIO | None = None,
) -> None:
    """Print one required variable path and declared unit per line."""
    for path, variable in required_inputs(
        block_id, model_catalog, library=library
    ).items():
        print(
            f"{path} [{variable.unit}]", file=file if file is not None else sys.stdout
        )
