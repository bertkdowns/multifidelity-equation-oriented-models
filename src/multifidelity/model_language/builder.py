"""Compile JSON equations or call explicitly registered symbolic providers."""

import ast
import operator
from collections.abc import Mapping
from copy import deepcopy

from idaes.core import FlowsheetBlock
from pyomo.core.expr.visitor import identify_variables
from pyomo.core.expr.numvalue import NumericValue
from pyomo.core.base.var import VarData
from pyomo.environ import Block, ConcreteModel, Constraint, ConstraintList, Var, units
from pyomo.util.check_units import assert_units_consistent

from .resolution import Library
from ._validation import connection_endpoints
from ._traversal import _walk_implementation
from .domains import BuildDomains
from .dynamics import build_derivatives
from .indexing import dotted_name, variable_dimensions


_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}


def _build_external_slice(active, external, variables, library, path, dependencies):
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
        for output, inputs in external.dependencies.items():
            dependencies[id(variables[output])] = {id(variables[name]) for name in inputs}
        active._model_language_initialization = (
            library.get_initializer(external.provider), deepcopy(external.config),
            dict(variables), dict(mapping), set(external.dependencies),
        )
        active._model_language_scaling = (
            library.get_scaler(external.provider), deepcopy(external.config),
            dict(variables), dict(mapping),
        )
    except Exception as error:
        raise ValueError(f"{path}: provider {external.provider!r}: {error}") from error


def _build_external(active, external, variables, library, path, dependencies):
    """Lift the scalar provider protocol over a shared time domain.

    A Block rule constructs new slices when DAE discretization inserts points.
    Scalar inputs are shared, while each time point has independent native state.
    """
    indexed = [v for v in variables.values() if v.is_indexed()]
    if not indexed:
        _build_external_slice(active, external, variables, library, path, dependencies)
        return
    time = indexed[0].index_set()

    def rule(block, t):
        public = {name: v[t] if v.is_indexed() else v for name, v in variables.items()}
        _build_external_slice(block, external, public, library, f"{path}[{t}]", dependencies)

    active.slices = Block(time, rule=rule)


def _expression(text, resolve, indices=None, index_domains=None):
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
            raise ValueError(f"Unsupported expression syntax: {text!r}")
        if isinstance(node, ast.Subscript) and indices is not None:
            name = dotted_name(node.value)
            items = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            if not all(isinstance(item, ast.Name) and item.id in indices for item in items):
                raise ValueError("Variable indices must be bound for_each names")
            return resolve(
                name, [indices[item.id] for item in items],
                [index_domains[item.id] for item in items],
            )
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            return _BINARY[type(node.op)](visit(node.left), visit(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        raise ValueError(f"Unsupported expression syntax: {ast.dump(node)}")

    return visit(ast.parse(text, mode="eval").body)


def build_model(model_id, implementation, *, library=None, domain_values=None,
                mode="steady", time_unit="s"):
    """Construct a steady or dynamic tree without solving or fixing operating inputs.

    implementation is an ImplementationDocument, dict or JSON file path. Every selected relationship must
    specify exactly its declared submodels, recursively. Recursive definitions
    are permitted only when the supplied selection terminates. All values and
    fixations, including initial conditions, are applied separately. Declared
    defaults supply unfixed starting guesses during construction.
    """
    from .implementation import ImplementationDocument
    from pathlib import Path
    if isinstance(implementation, (str, Path)):
        implementation = ImplementationDocument.load_json(implementation)
    elif not isinstance(implementation, ImplementationDocument):
        implementation = ImplementationDocument.model_validate(implementation)
    library = library or Library()
    root = library.resolve(model_id)
    build_domains = BuildDomains(root, domain_values, mode)

    def parse_unit(text):
        return _expression(text, lambda name: getattr(units, name))

    time_units = parse_unit(time_unit)
    units.convert(1 * time_units, to_units=units.s)

    model = ConcreteModel()
    model.fs = FlowsheetBlock(dynamic=mode == "dynamic", time_set=build_domains.time_points,
                              time_units=time_units)
    model.fs.root = Block()
    dependencies: dict[int, set[int]] = {}
    registry = {}
    initialization_order = []

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

    def enter(occurrence, parent, alias):
        """Create this occurrence's variables before visiting its children."""
        resolved = occurrence.model
        definition = resolved.definition
        path = resolved.path
        relationship = occurrence.relationship
        if parent is None:
            block, parent_domains = model.fs.root, None
        else:
            parent_block, _, parent_domains = parent
            block = Block()
            parent_block.relationship.models.add_component(alias, block)
        domains = build_domains.populate(block, resolved, parent_domains, model.fs.time)
        block.structs = Block()
        variables = {}
        # Struct blocks own variables. This lookup contains references to those
        # same objects, not copies; input direction does not imply fixation.
        for struct_id, struct in definition.structs.items():
            struct_block = Block()
            block.structs.add_component(struct_id, struct_block)
            for variable_id, variable in struct.variables.items():
                unit = parse_unit(variable.unit)
                sets = [domains[name] for name in variable.dimensions]
                if len({id(s) for s in sets}) != len(sets):
                    raise ValueError(f"{path}: variable dimensions must bind to distinct domains")
                var = Var(*sets, bounds=(variable.bounds.min, variable.bounds.max),
                          units=unit, initialize=variable.default)
                struct_block.add_component(variable_id, var)
                var._model_language_scale = variable.scale
                var._model_language_dimensions = tuple(variable.dimensions)
                if variable.scale is not None:
                    from idaes.core.util.scaling import set_scaling_factor
                    set_scaling_factor(var, variable.scale)
                variables[f"{struct_id}.{variable_id}"] = var
                registry[occurrence.prefix + f"{struct_id}.{variable_id}"] = var
        block.relationship = Block()
        active = block.relationship
        external = relationship.definition.external
        if external is not None:
            _build_external(
                active, external, variables, library,
                f"{path}.{occurrence.relationship_id}", dependencies,
            )
        else:
            active.models = Block()
        return block, variables, domains

    def leave(occurrence, context, children):
        """Compile equations after child interfaces and dependencies exist."""
        resolved = occurrence.model
        relationship = occurrence.relationship
        relationship_id = occurrence.relationship_id
        path = resolved.path
        block, variables, domains = context
        inputs = {
            occurrence.prefix + name: variable
            for name, variable in variables.items()
            if resolved.definition.structs[name.split('.')[0]].direction == 'input'
        }
        # A supplied input is still a boundary guess at its own local stage:
        # its parent's defining equation is outside that subtree. At ancestor
        # stages it is not independent, so only unsupplied inputs propagate up.
        open_inputs = {
            name: variable for name, variable in inputs.items()
            if name[len(occurrence.prefix):] not in occurrence.supplied
        }
        if relationship.definition.external is None:
            for child in block.relationship.models.component_objects(Block, descend_into=False):
                inherited = child._model_language_open_initialization_inputs
                inputs.update(inherited)
                open_inputs.update(inherited)
        block._model_language_open_initialization_inputs = open_inputs
        initialization_order.append((occurrence.prefix.rstrip('.') or model_id, block, inputs))
        active = block.relationship
        if relationship.definition.external is not None:
            return variables

        def resolve(reference, index_values=None, index_domains=None):
            # A relationship sees its parent's structs and its immediate
            # children's structs, but cannot reach into child relationships.
            component = None
            if reference in variables:
                component = variables[reference]
            alias, _, rest = reference.partition(".")
            if alias in children and rest in children[alias]:
                component = children[alias][rest]
            if component is not None:
                if component.is_indexed():
                    if index_values is None or len(index_values) != component.index_set().dimen:
                        raise ValueError(f"{path}: {reference!r} requires explicit indices matching its dimensions")
                    if tuple(index_domains) != variable_dimensions(resolved, relationship, reference):
                        raise ValueError(f"{path}: index domains do not match {reference!r}")
                    return component[tuple(index_values)]
                if index_values is not None:
                    raise ValueError(f"{path}: scalar variable {reference!r} cannot be indexed")
                return component
            # Dimensioned constants, e.g. 298.15 * units.K. Only a single
            # public unit name is allowed, never arbitrary attribute traversal.
            if index_values is None and alias == "units" and rest.isidentifier() and not rest.startswith("_"):
                try:
                    unit = getattr(units, rest)
                except AttributeError, ValueError:
                    unit = None
                if isinstance(unit, NumericValue):
                    return unit
            raise ValueError(f"{path}: unknown or inaccessible variable {reference!r}")

        # Pure definition checks are shared with required-input discovery.
        descendant_dependencies = dict(dependencies)
        build_derivatives(active, resolved, relationship, variables, domains,
                          mode, time_units, dependencies)

        active.constraints = Block()
        checks = []
        for name, equation in relationship.constraints.items():
            def rule(b, *index_values, equation=equation, name=name):
                if not equation.for_each:
                    index_values = ()
                indices = dict(zip(equation.for_each, index_values, strict=True))
                lhs = _expression(equation.lhs, resolve, indices, equation.for_each)
                rhs = _expression(equation.rhs, resolve, indices, equation.for_each)
                if isinstance(lhs == rhs, bool):
                    raise ValueError(f"{path}.{name}: equation must involve variables")
                target = equation.determines
                target_var = _expression(target, resolve, indices, equation.for_each)
                references = {id(v) for v in identify_variables(lhs - rhs)}
                checks.append((name, target, id(target_var), references))
                dependencies[id(target_var)] = references - {id(target_var)}
                return lhs == rhs

            active.constraints.add_component(
                name, Constraint(*(domains[d] for d in equation.for_each.values()), rule=rule)
            )
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
                def component(reference):
                    if reference in variables:
                        return variables[reference]
                    alias, _, rest = reference.partition(".")
                    return children[alias][rest]

                a = component(source[1] + "." + field)
                b = component(target[1] + "." + field)

                def connect(_, *indices, a=a, b=b):
                    av, bv = (a[indices], b[indices]) if a.is_indexed() else (a, b)
                    dependencies[id(bv)] = {id(av)}
                    return av == units.convert(bv, to_units=units.get_units(av))

                connection_block.add_component(
                    field, Constraint(*(a.index_set().subsets() if a.is_indexed() else ()), rule=connect),
                )
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

    _walk_implementation(root, implementation, enter, leave)
    build_domains.check_unused()
    # Check the complete equation tree without fixing values or calling a solver.
    assert_units_consistent(model)
    # Retain the same occurrence-path lookup for later specification application.
    # Components stay live as discretization adds entries to indexed variables.
    model._model_language_model_id = model_id
    model._model_language_implementation = implementation.model_copy(deep=True)
    model._model_language_variables = registry
    model._model_language_initialization_order = initialization_order
    return model
