"""Derive required input specifications from explicit relationship selections."""

from pathlib import Path
from typing import TextIO
import sys

from .definitions import Connection, Struct, Variable
from .implementation import ImplementationDocument
from .indexing import (
    derivative_variables, equation_target, target_reference, validate_domains,
    variable_dimensions,
)
from .resolution import Library, ModelView, RelationshipView


def connection_endpoints(
    model: ModelView,
    relationship: RelationshipView,
    connection: Connection,
    path: str,
) -> tuple[tuple[Struct, str, bool], tuple[Struct, str, bool]]:
    """Resolve structs and check direction/fields without constructing equations."""
    endpoints = []
    for endpoint in (connection.from_, connection.to):
        alias, sep, struct_id = endpoint.partition(".")
        if sep:
            if alias not in relationship.models:
                raise ValueError(f"{path}: unknown child in connection {endpoint}")
            definition, prefix = relationship.models[alias], alias + "."
        else:
            definition, struct_id, prefix = model, alias, ""
        if struct_id not in definition.structs:
            raise ValueError(f"{path}: unknown struct {endpoint}")
        endpoints.append((definition.structs[struct_id], prefix + struct_id, bool(sep)))
    source, target = endpoints
    if source[0].direction != ("output" if source[2] else "input") or target[
        0
    ].direction != ("input" if target[2] else "output"):
        raise ValueError(f"{path}: invalid connection direction")
    if set(source[0].variables) != set(target[0].variables):
        raise ValueError(f"{path}: connection fields differ")
    for field in source[0].variables:
        a = variable_dimensions(model, relationship, source[1] + "." + field)
        b = variable_dimensions(model, relationship, target[1] + "." + field)
        if a != b:
            raise ValueError(f"{path}: connection dimensions differ for {field!r}")
    return source, target


def determination_sources(model: ModelView, relationship_id: str) -> dict[str, str]:
    """Share coverage/duplicate checks between input discovery and the backend.

    This checks declarations, not mathematical determinacy or equation syntax.
    """
    relationship = model.relationships[relationship_id]
    validate_domains(model)
    path = f"{model.path}.{relationship_id}"
    outputs = {
        f"{s}.{v}"
        for s, struct in model.structs.items()
        if struct.direction == "output"
        for v in struct.variables
    }
    external = relationship.definition.external
    if external is not None:
        timed = any(v.dimensions for s in model.structs.values() for v in s.variables.values())
        for struct in model.structs.values():
            for variable in struct.variables.values():
                if variable.dimensions and (
                    len(variable.dimensions) != 1
                    or model.definition.domains[variable.dimensions[0]].kind != "time"
                ):
                    raise ValueError(f"{path}: external providers support only scalar or time-indexed fields")
                if timed and struct.direction == "output" and not variable.dimensions:
                    raise ValueError(f"{path}: time-sliced providers require time-indexed outputs")
        # Authored dependencies stand in for JSON equation determinations. They
        # are never checked against the provider's internal equations.
        inputs = {
            f"{s}.{v}"
            for s, struct in model.structs.items()
            if struct.direction == "input"
            for v in struct.variables
        }
        if set(external.dependencies) != outputs:
            raise ValueError(
                f"{path}: external dependencies must declare exactly the public outputs"
            )
        for output, dependencies in external.dependencies.items():
            if set(dependencies) - inputs:
                raise ValueError(
                    f"{path}: dependencies for {output!r} must name public inputs"
                )
        return {output: f"provider {external.provider}" for output in outputs}
    allowed = outputs | {
        f"{alias}.{s}.{v}"
        for alias, child in relationship.models.items()
        for s, struct in child.structs.items()
        if struct.direction == "input"
        for v in struct.variables
    }
    sources = {}

    def register(target, source):
        if target not in allowed:
            raise ValueError(
                f"{path}: {source} determines invalid target {target!r}; expected a parent output or immediate child input"
            )
        if target in sources:
            raise ValueError(
                f"{path}: duplicate determination of {target!r} by {sources[target]} and {source}"
            )
        sources[target] = source

    for name, equation in relationship.constraints.items():
        # Check allowed targets first to preserve scope/direction diagnostics.
        target, _ = target_reference(equation.determines)
        register(target, f"constraint {name}")
        equation_target(model, relationship, equation)
    derivative_states = set()
    for name, derivative in relationship.derivatives.items():
        derivative_variables(model, derivative)
        key = (derivative.state, derivative.with_respect_to)
        if key in derivative_states:
            raise ValueError(f"{path}: duplicate derivative of {derivative.state!r}")
        derivative_states.add(key)
        register(derivative.determines, f"derivative {name}")
    for name, connection in relationship.connections.items():
        _, target = connection_endpoints(
            model, relationship, connection, f"{path}.{name}"
        )
        for field in target[0].variables:
            register(f"{target[1]}.{field}", f"connection {name}")
    missing = sorted(outputs - sources.keys())
    if missing:
        raise ValueError(
            f"{path}: missing output determinations: " + ", ".join(missing)
        )
    return sources


def _selected_occurrences(model_id, implementation, library):
    """Validate selections once for both kinds of specification discovery."""
    if isinstance(implementation, (str, Path)):
        implementation = ImplementationDocument.model_validate_json(
            Path(implementation).read_text()
        )
    elif not isinstance(implementation, ImplementationDocument):
        implementation = ImplementationDocument.model_validate(implementation)
    if implementation.model != model_id:
        raise ValueError("Root implementation must identify the requested model")
    library = library or Library()

    def visit(model, selection, prefix, supplied):
        if selection.model is not None and selection.model != model.id:
            raise ValueError(f"{model.path}: implementation model does not match reference")
        if selection.relationship not in model.relationships:
            raise ValueError(f"{model.path}: unknown relationship {selection.relationship!r}")
        relationship = model.relationships[selection.relationship]
        if set(selection.submodels) != set(relationship.models):
            raise ValueError(f"{model.path}: submodels must be exactly {sorted(relationship.models)}")
        sources = determination_sources(model, selection.relationship)
        yield model, relationship, prefix, supplied
        for alias, child in relationship.models.items():
            child_prefix = alias + "."
            child_supplied = {
                target[len(child_prefix):] for target in sources
                if target.startswith(child_prefix)
            }
            yield from visit(
                child, selection.submodels[alias], prefix + child_prefix, child_supplied
            )

    yield from visit(library.resolve(model_id), implementation, "", set())


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
