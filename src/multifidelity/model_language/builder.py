"""Scalar equation compiler; no execution of Python supplied by model documents."""

import ast
import json
import operator
from pathlib import Path

from idaes.core import FlowsheetBlock
from pyomo.core.expr.visitor import identify_variables
from pyomo.core.base.units_container import UnitsError
from pyomo.environ import Block, ConcreteModel, Constraint, Var, units
from pyomo.util.check_units import assert_units_consistent


class Library:
    """An ID-indexed collection of model documents."""

    def __init__(self, directory=None):
        directory = Path(directory) if directory else Path(__file__).parent / "models"
        self.models = {}
        # References use document IDs, so moving or renaming a file does not
        # change which definition a relationship refers to.
        for path in sorted(directory.glob("*.json")):
            document = json.loads(path.read_text())
            name = document["id"]
            if name in self.models:
                raise ValueError(f"Duplicate model ID: {name}")
            self.models[name] = document

    def get(self, name):
        try:
            return self.models[name]
        except KeyError:
            raise ValueError(f"Unknown model: {name}") from None


_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}


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


def _name(name):
    """Keep component names compatible with dotted references; reserve '_' names."""
    if not name.isidentifier() or name.startswith("_"):
        raise ValueError(f"Invalid identifier: {name!r}")
    return name


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
    if library.get(model_id).get("model_parameters"):
        raise ValueError(
            "Root generic models are not supported; use a concrete wrapper"
        )

    def check_interface(definition, requirement, path):
        # Requirements are structural: extra structs and properties are allowed.
        for struct_id, expected in requirement.get("requires", {}).items():
            actual = definition["structs"].get(struct_id)
            if actual is None or actual["direction"] != expected["direction"]:
                raise ValueError(f"{path}: incompatible required struct {struct_id!r}")
            for name, variable in expected["variables"].items():
                supplied = actual["variables"].get(name)
                if supplied is None:
                    raise ValueError(
                        f"{path}: missing required variable {struct_id}.{name}"
                    )
                for key, default in (("value_type", "real"), ("dimensions", [])):
                    if supplied.get(key, default) != variable.get(key, default):
                        raise ValueError(
                            f"{path}: incompatible {key} for {struct_id}.{name}"
                        )

                def unit(spec):
                    return _expression(
                        spec.get("unit", "dimensionless"),
                        lambda name: getattr(units, name),
                    )

                try:
                    units.convert(unit(supplied), to_units=unit(variable))
                except UnitsError as error:
                    raise ValueError(
                        f"{path}: incompatible units for {struct_id}.{name}"
                    ) from error

    def reference_target(reference, parameters, path):
        """Resolve definitions and generic arguments without changing library data.

        Parameter environments belong to occurrences, not reusable definitions;
        two uses of a generic model can therefore supply different arguments.
        """
        if ("model" in reference) == ("model_parameter" in reference):
            raise ValueError(f"{path}: specify exactly one of model or model_parameter")
        if "model_parameter" in reference:
            name = reference["model_parameter"]
            if name not in parameters:
                raise ValueError(f"{path}: unknown model parameter {name!r}")
            if "model_arguments" in reference:
                raise ValueError(
                    f"{path}: forwarded parameters already have their arguments"
                )
            return parameters[name]
        target = reference["model"]
        definition = library.get(target)
        declarations = definition.get("model_parameters", {})
        arguments = reference.get("model_arguments", {})
        if set(arguments) != set(declarations):
            raise ValueError(
                f"{path}: model arguments must be exactly {sorted(declarations)}"
            )
        resolved = {}
        for name, requirement in declarations.items():
            _name(name)
            argument = reference_target(arguments[name], parameters, f"{path}<{name}>")
            check_interface(library.get(argument[0]), requirement, f"{path}<{name}>")
            resolved[name] = argument
        return target, resolved

    model = ConcreteModel()
    model.fs = FlowsheetBlock(dynamic=False)
    model.fs.root = Block()

    def populate(block, definition_id, selection, path, parameters):
        """Build one occurrence and return only its public variable references.

        Each call creates fresh components, even when several occurrences share
        a definition. ``path`` identifies the occurrence in validation errors.
        """
        definition = library.get(definition_id)
        if selection.get("model", definition_id) != definition_id:
            raise ValueError(f"{path}: implementation model does not match reference")
        relationship_id = selection.get("relationship")
        if relationship_id not in definition["relationships"]:
            raise ValueError(
                f"{path}: unknown or missing relationship {relationship_id!r}"
            )
        relationship = definition["relationships"][relationship_id]
        refs = relationship.get("models", {})
        targets = {
            alias: reference_target(reference, parameters, f"{path}.{alias}")
            for alias, reference in refs.items()
        }
        selected = selection.get("submodels", {})
        # Validate against the selected relationship only: alternatives may have
        # entirely different children and are not materialized in this build.
        if set(selected) != set(refs):
            raise ValueError(f"{path}: submodels must be exactly {sorted(refs)}")
        block.structs = Block()
        variables = {}
        # Struct blocks own variables. This lookup contains references to those
        # same objects, not copies; input direction does not imply fixation.
        for struct_id, struct in definition["structs"].items():
            _name(struct_id)
            if struct["direction"] not in ("input", "output"):
                raise ValueError(f"{path}.{struct_id}: invalid direction")
            struct_block = Block()
            block.structs.add_component(struct_id, struct_block)
            for variable_id, variable in struct["variables"].items():
                _name(variable_id)
                if variable.get("dimensions"):
                    raise ValueError(f"{path}: indexed variables are not supported yet")
                if variable.get("value_type", "real") != "real":
                    raise ValueError(f"{path}: only real variables are supported")
                unit = _expression(
                    variable.get("unit", "dimensionless"),
                    lambda name: getattr(units, name),
                )
                bounds = variable.get("bounds", {})
                var = Var(bounds=(bounds.get("min"), bounds.get("max")), units=unit)
                struct_block.add_component(variable_id, var)
                variables[f"{struct_id}.{variable_id}"] = var
        block.relationship = Block()
        active = block.relationship
        active.models = Block()
        children = {}
        # Build children before equations so all referenced variables exist.
        # Local aliases distinguish repeated uses of the same model definition.
        for alias, reference in refs.items():
            _name(alias)
            child = Block()
            active.models.add_component(alias, child)
            children[alias] = populate(
                child,
                targets[alias][0],
                selected[alias],
                f"{path}.{alias}",
                targets[alias][1],
            )

        def resolve(reference):
            # A relationship sees its parent's structs and its immediate
            # children's structs, but cannot reach into child relationships.
            if reference in variables:
                return variables[reference]
            alias, _, rest = reference.partition(".")
            if alias in children and rest in children[alias]:
                return children[alias][rest]
            raise ValueError(f"{path}: unknown or inaccessible variable {reference!r}")

        # Only parent outputs and immediate child inputs may be determined here.
        # Other child inputs may remain unspecified for a future instance to set.
        outputs = {
            f"{s}.{v}"
            for s, struct in definition["structs"].items()
            if struct["direction"] == "output"
            for v in struct["variables"]
        }
        allowed = outputs | {
            f"{alias}.{s}.{v}"
            for alias, (target_id, _) in targets.items()
            for s, struct in library.get(target_id)["structs"].items()
            if struct["direction"] == "input"
            for v in struct["variables"]
        }
        determinations = {}

        def determine(target, source):
            if not isinstance(target, str) or target not in allowed:
                raise ValueError(
                    f"{path}.{relationship_id}: {source} determines invalid target "
                    f"{target!r}; expected a parent output or immediate child input"
                )
            if target in determinations:
                raise ValueError(
                    f"{path}.{relationship_id}: duplicate determination of {target!r} "
                    f"by {determinations[target]} and {source}"
                )
            determinations[target] = source

        active.constraints = Block()
        for name, equation in relationship.get("constraints", {}).items():
            _name(name)
            lhs = _expression(equation["lhs"], resolve)
            rhs = _expression(equation["rhs"], resolve)
            # A comparison of plain numbers produces a Python bool rather than
            # a symbolic equation, and cannot constrain the constructed model.
            if isinstance(lhs == rhs, bool):
                raise ValueError(f"{path}.{name}: equation must involve variables")
            target = equation.get("determines")
            determine(target, f"constraint {name}")
            target_var = resolve(target)
            if not any(v is target_var for v in identify_variables(lhs - rhs)):
                raise ValueError(
                    f"{path}.{relationship_id}: constraint {name} determines "
                    f"{target!r}, but it does not occur in the equation"
                )
            active.constraints.add_component(name, Constraint(expr=lhs == rhs))
        active.connections = Block()
        # Connections are shorthand for field-by-field equality constraints;
        # no Arc objects, variable aliases, or arc expansion are involved.
        for name, connection in relationship.get("connections", {}).items():
            _name(name)
            endpoints = []
            for endpoint in (connection["from"], connection["to"]):
                # "struct" names a parent interface; "child.struct" names a
                # child interface. Record whether each endpoint is a child so
                # direction can be interpreted from inside this relationship.
                alias, sep, struct_id = endpoint.partition(".")
                if sep:
                    if alias not in refs:
                        raise ValueError(
                            f"{path}: unknown child in connection {endpoint}"
                        )
                    doc = library.get(targets[alias][0])
                    prefix = alias + "."
                else:
                    doc, struct_id, prefix = definition, alias, ""
                if struct_id not in doc["structs"]:
                    raise ValueError(f"{path}: unknown struct {endpoint}")
                endpoints.append(
                    (doc["structs"][struct_id], prefix + struct_id, bool(sep))
                )
            source, target = endpoints
            # Parent inputs feed children; child outputs feed parent outputs.
            expected_source = "output" if source[2] else "input"
            expected_target = "input" if target[2] else "output"
            if (
                source[0]["direction"] != expected_source
                or target[0]["direction"] != expected_target
            ):
                raise ValueError(f"{path}.{name}: invalid connection direction")
            if set(source[0]["variables"]) != set(target[0]["variables"]):
                raise ValueError(f"{path}.{name}: connection fields differ")
            connection_block = Block()
            active.connections.add_component(name, connection_block)
            for field in source[0]["variables"]:
                determine(target[1] + "." + field, f"connection {name}")
                a, b = (
                    resolve(source[1] + "." + field),
                    resolve(target[1] + "." + field),
                )
                # Convert compatible units; incompatible dimensions raise here.
                connection_block.add_component(
                    field,
                    Constraint(expr=a == units.convert(b, to_units=units.get_units(a))),
                )
        missing = sorted(outputs - determinations.keys())
        if missing:
            raise ValueError(
                f"{path}.{relationship_id}: missing output determinations: "
                + ", ".join(missing)
            )
        # Export only this model's interface, preserving encapsulation when the
        # containing relationship resolves references to this occurrence.
        return variables

    populate(model.fs.root, model_id, implementation, model_id, {})
    # Check the complete equation tree without fixing values or calling a solver.
    assert_units_consistent(model)
    return model
