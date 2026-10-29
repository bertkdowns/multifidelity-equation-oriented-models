"""Compile JSON equations or call explicitly registered symbolic providers."""

import ast
import json
import operator
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path

from idaes.core import FlowsheetBlock
from pyomo.core.expr.visitor import identify_variables
from pyomo.core.expr.numvalue import NumericValue
from pyomo.core.base.var import VarData
from pyomo.environ import Block, ConcreteModel, Constraint, ConstraintList, Var, units
from pyomo.util.check_units import assert_units_consistent

from .resolution import Library, ResolvedModel
from .requirements import connection_endpoints, determination_sources


_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}


def _build_external(active, external, variables, library, path):
    """Keep provider construction and interface binding out of JSON compilation."""
    active.provider = Block()
    try:
        provider = library.get_provider(external.provider)
        mapping = provider(active.provider, deepcopy(external.config))
        if not isinstance(mapping, Mapping) or set(mapping) != set(variables):
            raise ValueError(
                "Provider mapping must contain exactly the public variable paths"
            )
        active.bindings = ConstraintList()
        for name, public in variables.items():
            internal = mapping[name]
            if not isinstance(internal, VarData):
                raise ValueError(
                    f"Mapping for {name!r} must be a scalar Pyomo variable"
                )
            active.bindings.add(
                public == units.convert(internal, to_units=units.get_units(public))
            )
    except Exception as error:
        raise ValueError(f"{path}: provider {external.provider!r}: {error}") from error


def _expression(text, resolve):
    """Translate allowed arithmetic into Pyomo expressions using a scoped resolver.

    The same parser handles variable expressions and unit expressions; the
    resolver determines what names mean in each context. Parsing Python syntax
    does not execute it: only the node types explicitly handled below are allowed.
    """

    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.Name):
            return resolve(node.id)
        if isinstance(node, ast.Attribute):
            # Treat dotted syntax as a reference, not Python attribute access.
            # The resolver enforces which model variables are visible.
            parts = []
            while isinstance(node, ast.Attribute):
                parts.append(node.attr)
                node = node.value
            if isinstance(node, ast.Name):
                return resolve(".".join([node.id, *reversed(parts)]))
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            return _BINARY[type(node.op)](visit(node.left), visit(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        raise ValueError(f"Unsupported expression syntax: {ast.dump(node)}")

    return visit(ast.parse(text, mode="eval").body)


def build_model(model_id, implementation, *, library=None):
    """Construct, without fixing inputs or solving, a selected model tree.

    implementation is a dict or JSON file path. Every selected relationship must
    specify exactly its declared submodels, recursively. Recursive definitions
    are permitted only when the supplied selection terminates.
    """
    library = library or Library()
    if isinstance(implementation, (str, Path)):
        implementation = json.loads(Path(implementation).read_text())
    if implementation.get("model") != model_id:
        raise ValueError("Root implementation must identify the requested model")
    root = library.resolve(model_id)

    model = ConcreteModel()
    model.fs = FlowsheetBlock(dynamic=False)
    model.fs.root = Block()
    dependencies: dict[int, set[int]] = {}

    def depends_on(expression_variables, target, graph):
        pending = list(expression_variables)
        visited = set()
        while pending:
            current = pending.pop()
            if current == target:
                return True
            if current not in visited:
                visited.add(current)
                pending.extend(graph.get(current, ()))
        return False

    def populate(block, resolved: ResolvedModel, selection):
        """Build one occurrence and return only its public variable references.

        Each call creates fresh components, even when several occurrences share
        a definition. ``path`` identifies the occurrence in validation errors.
        """
        definition = resolved.definition
        definition_id, path = resolved.id, resolved.path
        if selection.get("model", definition_id) != definition_id:
            raise ValueError(f"{path}: implementation model does not match reference")
        relationship_id = selection.get("relationship")
        if relationship_id not in definition.relationships:
            raise ValueError(
                f"{path}: unknown or missing relationship {relationship_id!r}"
            )
        relationship = resolved.relationships[relationship_id]
        refs = relationship.models
        selected = selection.get("submodels", {})
        # Validate against the selected relationship only: alternatives may have
        # entirely different children and are not materialized in this build.
        if set(selected) != set(refs):
            raise ValueError(f"{path}: submodels must be exactly {sorted(refs)}")
        block.structs = Block()
        variables = {}
        # Struct blocks own variables. This lookup contains references to those
        # same objects, not copies; input direction does not imply fixation.
        for struct_id, struct in definition.structs.items():
            struct_block = Block()
            block.structs.add_component(struct_id, struct_block)
            for variable_id, variable in struct.variables.items():
                if variable.dimensions:
                    raise ValueError(f"{path}: indexed variables are not supported yet")
                unit = _expression(
                    variable.unit,
                    lambda name: getattr(units, name),
                )
                var = Var(bounds=(variable.bounds.min, variable.bounds.max), units=unit)
                struct_block.add_component(variable_id, var)
                variables[f"{struct_id}.{variable_id}"] = var
        block.relationship = Block()
        active = block.relationship
        external = relationship.definition.external
        if external is not None:
            determination_sources(resolved, relationship_id)
            _build_external(
                active, external, variables, library, f"{path}.{relationship_id}"
            )
            for output, inputs in external.dependencies.items():
                dependencies[id(variables[output])] = {
                    id(variables[name]) for name in inputs
                }
            return variables
        active.models = Block()
        children = {}
        # Build children before equations so all referenced variables exist.
        # Local aliases distinguish repeated uses of the same model definition.
        for alias, reference in refs.items():
            child = Block()
            active.models.add_component(alias, child)
            children[alias] = populate(
                child,
                reference,
                selected[alias],
            )

        def resolve(reference):
            # A relationship sees its parent's structs and its immediate
            # children's structs, but cannot reach into child relationships.
            if reference in variables:
                return variables[reference]
            alias, _, rest = reference.partition(".")
            if alias in children and rest in children[alias]:
                return children[alias][rest]
            # Dimensioned constants, e.g. 298.15 * units.K. Only a single
            # public unit name is allowed, never arbitrary attribute traversal.
            if alias == "units" and rest.isidentifier() and not rest.startswith("_"):
                try:
                    unit = getattr(units, rest)
                except AttributeError, ValueError:
                    unit = None
                if isinstance(unit, NumericValue):
                    return unit
            raise ValueError(f"{path}: unknown or inaccessible variable {reference!r}")

        # Pure definition checks are shared with required-input discovery.
        determination_sources(resolved, relationship_id)
        descendant_dependencies = dict(dependencies)

        active.constraints = Block()
        checks = []
        for name, equation in relationship.constraints.items():
            lhs = _expression(equation.lhs, resolve)
            rhs = _expression(equation.rhs, resolve)
            # A comparison of plain numbers produces a Python bool rather than
            # a symbolic equation, and cannot constrain the constructed model.
            if isinstance(lhs == rhs, bool):
                raise ValueError(f"{path}.{name}: equation must involve variables")
            target = equation.determines
            target_var = resolve(target)
            references = {id(v) for v in identify_variables(lhs - rhs)}
            checks.append((name, target, id(target_var), references))
            active.constraints.add_component(name, Constraint(expr=lhs == rhs))
            dependencies[id(target_var)] = references - {id(target_var)}
        active.connections = Block()
        # Connections are shorthand for field-by-field equality constraints;
        # no Arc objects, variable aliases, or arc expansion are involved.
        for name, connection in relationship.connections.items():
            source, target = connection_endpoints(
                resolved, relationship, connection, f"{path}.{name}"
            )
            connection_block = Block()
            active.connections.add_component(name, connection_block)
            for field in source[0].variables:
                a, b = (
                    resolve(source[1] + "." + field),
                    resolve(target[1] + "." + field),
                )
                # Convert compatible units; incompatible dimensions raise here.
                connection_block.add_component(
                    field,
                    Constraint(expr=a == units.convert(b, to_units=units.get_units(a))),
                )
                dependencies[id(b)] = {id(a)}
        # Only previously validated descendants can justify an indirect target.
        # Local declarations must not validate one another through invented cycles.
        for name, target, target_id, references in checks:
            if not depends_on(references, target_id, descendant_dependencies):
                raise ValueError(
                    f"{path}.{relationship_id}: constraint {name} determines "
                    f"{target!r}, but it does not occur in the equation or its child dependencies"
                )
        # Export only this model's interface, preserving encapsulation when the
        # containing relationship resolves references to this occurrence.
        return variables

    populate(model.fs.root, root, implementation)
    # Check the complete equation tree without fixing values or calling a solver.
    assert_units_consistent(model)
    return model
