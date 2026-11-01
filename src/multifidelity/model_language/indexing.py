"""Definition-level index signatures, shared by discovery and construction."""

import ast


def dotted_name(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        return ".".join([node.id, *reversed(parts)])
    raise ValueError("Expected a dotted variable reference")


def target_reference(text):
    """Determinations cover a whole family, once, with named loop indices."""
    node = ast.parse(text, mode="eval").body
    indices = []
    if isinstance(node, ast.Subscript):
        items = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        if not all(isinstance(item, ast.Name) for item in items):
            raise ValueError("Determination indices must be for_each names")
        indices = [item.id for item in items]
        node = node.value
    return dotted_name(node), indices


def validate_domains(model):
    for struct in model.structs.values():
        for variable in struct.variables.values():
            unknown = set(variable.dimensions) - model.definition.domains.keys()
            if unknown:
                raise ValueError(f"{model.path}: unknown variable domains {sorted(unknown)}")


def variable_dimensions(model, relationship, reference):
    """Express an immediate child's dimensions in its parent's namespace."""
    parts = reference.split(".")
    if len(parts) == 2:
        owner = model
        bindings = {name: name for name in model.definition.domains}
    elif len(parts) == 3 and parts[0] in relationship.models:
        owner = relationship.models[parts.pop(0)]
        bindings = owner.domain_bindings
    else:
        raise ValueError(f"{model.path}: unknown variable {reference!r}")
    try:
        dimensions = owner.structs[parts[0]].variables[parts[1]].dimensions
        return tuple(bindings[dimension] for dimension in dimensions)
    except KeyError:
        raise ValueError(
            f"{model.path}: unknown variable or unbound child domain in {reference!r}"
        ) from None


def equation_target(model, relationship, equation):
    target, indices = target_reference(equation.determines)
    unknown = set(equation.for_each.values()) - model.definition.domains.keys()
    if unknown:
        raise ValueError(f"{model.path}: unknown for_each domains {sorted(unknown)}")
    dimensions = variable_dimensions(model, relationship, target)
    # Requiring exactly the target's dimensions prevents partial coverage and
    # accidentally repeating a scalar determination across an extra domain.
    if (
        len(indices) != len(set(indices))
        or set(indices) != set(equation.for_each)
        or tuple(equation.for_each[index] for index in indices) != dimensions
    ):
        raise ValueError(
            f"{model.path}: determines {equation.determines!r} must cover exactly its dimensions"
        )
    return target
