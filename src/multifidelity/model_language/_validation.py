"""Definition-level connection and determination checks shared by traversal and build."""

from .definitions import Connection, Struct
from .indexing import (
    derivative_variables, equation_target, target_reference, validate_domains,
    variable_dimensions,
)
from .resolution import BlockView, FormulationView


def connection_endpoints(
    model: BlockView,
    formulation: FormulationView,
    connection: Connection,
    path: str,
) -> tuple[tuple[Struct, str, bool], tuple[Struct, str, bool]]:
    """Resolve structs and check direction/fields without constructing equations."""
    endpoints = []
    for endpoint in (connection.from_, connection.to):
        alias, sep, struct_id = endpoint.partition(".")
        if sep:
            if alias not in formulation.blocks:
                raise ValueError(f"{path}: unknown child in connection {endpoint}")
            definition, prefix = formulation.blocks[alias], alias + "."
        else:
            definition, struct_id, prefix = model, alias, ""
        if struct_id not in definition.structs:
            raise ValueError(f"{path}: unknown struct {endpoint}")
        endpoints.append((definition.structs[struct_id], prefix + struct_id, bool(sep)))
    source, target = endpoints
    # Child inputs and outputs are both readable by their containing formulation.
    # Only destinations declare responsibility for determining a variable.
    if target[0].direction != ("input" if target[2] else "output"):
        raise ValueError(f"{path}: invalid connection direction")
    if source[1] == target[1]:
        raise ValueError(f"{path}: connection endpoints must differ")
    if set(source[0].variables) != set(target[0].variables):
        raise ValueError(f"{path}: connection fields differ")
    for field in source[0].variables:
        a = variable_dimensions(model, formulation, source[1] + "." + field)
        b = variable_dimensions(model, formulation, target[1] + "." + field)
        if a != b:
            raise ValueError(f"{path}: connection dimensions differ for {field!r}")
    return source, target


def determination_sources(model: BlockView, formulation_id: str) -> dict[str, str]:
    """Share coverage/duplicate checks between input discovery and the backend.

    This checks declarations, not mathematical determinacy or equation syntax.
    """
    formulation = model.formulations[formulation_id]
    validate_domains(model)
    path = f"{model.path}.{formulation_id}"
    outputs = {
        f"{s}.{v}"
        for s, struct in model.structs.items()
        if struct.direction == "output"
        for v in struct.variables
    }
    external = formulation.definition.external
    if external is not None:
        timed = any(v.dimensions for s in model.structs.values() for v in s.variables.values())
        for struct in model.structs.values():
            for variable in struct.variables.values():
                if variable.dimensions and (
                    len(variable.dimensions) != 1
                    or model.definition.domains[variable.dimensions[0]].kind != "time"
                ):
                    raise ValueError(f"{path}: external feeds support only scalar or time-indexed fields")
                if timed and struct.direction == "output" and not variable.dimensions:
                    raise ValueError(f"{path}: time-sliced feeds require time-indexed outputs")
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
        for alias, child in formulation.blocks.items()
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

    for name, equation in formulation.constraints.items():
        # Check allowed targets first to preserve scope/direction diagnostics.
        target, _ = target_reference(equation.determines)
        register(target, f"constraint {name}")
        equation_target(model, formulation, equation)
    derivative_states = set()
    for name, derivative in formulation.derivatives.items():
        derivative_variables(model, derivative)
        key = (derivative.state, derivative.with_respect_to)
        if key in derivative_states:
            raise ValueError(f"{path}: duplicate derivative of {derivative.state!r}")
        derivative_states.add(key)
        register(derivative.determines, f"derivative {name}")
    for name, connection in formulation.connections.items():
        _, target = connection_endpoints(
            model, formulation, connection, f"{path}.{name}"
        )
        for field in target[0].variables:
            register(f"{target[1]}.{field}", f"connection {name}")
    missing = sorted(outputs - sources.keys())
    if missing:
        raise ValueError(
            f"{path}: missing output determinations: " + ", ".join(missing)
        )
    return sources


