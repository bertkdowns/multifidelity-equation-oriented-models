"""Load and navigate definition references without constructing solver objects."""

from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import pint

from .definitions import (
    ModelDocument,
    ModelParameter,
    ModelReference,
    ParameterModelReference,
    Relationship,
)
from .providers import Provider


# Unit compatibility is a property of definitions, not of the Pyomo backend.
_UNITS = pint.UnitRegistry()


def _check_interface(definition: ModelDocument, requirement: ModelParameter, path: str):
    for struct_id, expected in requirement.requires.items():
        actual = definition.structs.get(struct_id)
        if actual is None or actual.direction != expected.direction:
            raise ValueError(f"{path}: incompatible required struct {struct_id!r}")
        for name, variable in expected.variables.items():
            supplied = actual.variables.get(name)
            if supplied is None:
                raise ValueError(
                    f"{path}: missing required variable {struct_id}.{name}"
                )
            for key in ("value_type", "dimensions"):
                if getattr(supplied, key) != getattr(variable, key):
                    raise ValueError(
                        f"{path}: incompatible {key} for {struct_id}.{name}"
                    )
            try:
                compatible = _UNITS.Unit(supplied.unit).is_compatible_with(
                    _UNITS.Unit(variable.unit)
                )
            except (pint.PintError, ValueError) as error:
                raise ValueError(
                    f"{path}: invalid units for {struct_id}.{name}"
                ) from error
            if not compatible:
                raise ValueError(f"{path}: incompatible units for {struct_id}.{name}")


class Library:
    """An ID-indexed library of typed documents with resolved navigation views."""

    def __init__(self, directory=None):
        directory = Path(directory) if directory else Path(__file__).parent / "models"
        self.models: dict[str, ModelDocument] = {}
        self._providers: dict[str, Provider] = {}
        for path in sorted(directory.glob("*.json")):
            document = ModelDocument.load_json(path)
            if document.id in self.models:
                raise ValueError(f"Duplicate model ID: {document.id}")
            self.models[document.id] = document

    def register_provider(self, name: str, provider: Provider) -> None:
        """Register trusted Python code; definitions only store its stable name."""
        if name in self._providers:
            raise ValueError(f"Duplicate provider: {name}")
        self._providers[name] = provider

    def get_provider(self, name: str) -> Provider:
        """Resolve a provider only when its external relationship is built."""
        try:
            return self._providers[name]
        except KeyError:
            raise ValueError(f"Unknown provider: {name}") from None

    def get(self, name: str) -> ModelDocument:
        try:
            return self.models[name]
        except KeyError:
            raise ValueError(f"Unknown model: {name}") from None

    def resolve(self, name: str) -> "ModelView":
        """Open a concrete root; resolve descendants automatically as accessed.

        Each call creates a fresh navigation view. Treat definitions as unchanged
        while using that view; open a new view after editing library documents.
        """
        definition = self.get(name)
        if definition.model_parameters:
            raise ValueError(
                "Root generic models are not supported; use a concrete wrapper"
            )
        return ModelView(definition, {}, self, name)

    def _reference(
        self, reference: ModelReference, parameters, path: str
    ) -> "ModelView":
        if isinstance(reference, ParameterModelReference):
            name = reference.model_parameter
            if name not in parameters:
                raise ValueError(f"{path}: unknown model parameter {name!r}")
            argument = parameters[name]
            return ModelView(
                argument.definition, argument.model_arguments, self, path,
                dict(reference.domain_bindings),
            )
        definition = self.get(reference.model)
        declarations = definition.model_parameters
        if set(reference.model_arguments) != set(declarations):
            raise ValueError(
                f"{path}: model arguments must be exactly {sorted(declarations)}"
            )
        arguments = {}
        for name, requirement in declarations.items():
            argument = self._reference(
                reference.model_arguments[name], parameters, f"{path}<{name}>"
            )
            _check_interface(argument.definition, requirement, f"{path}<{name}>")
            arguments[name] = argument
        return ModelView(definition, arguments, self, path, dict(reference.domain_bindings))


@dataclass(eq=False)
class ModelView:
    """A shared definition viewed in one generic-argument and reference context."""

    definition: ModelDocument
    model_arguments: dict[str, "ModelView"]
    _library: Library
    path: str
    domain_bindings: dict[str, str] = field(default_factory=dict)

    @property
    def id(self):
        return self.definition.id

    @property
    def structs(self):
        return self.definition.structs

    @cached_property
    def relationships(self) -> dict[str, "RelationshipView"]:
        # Do not traverse descendants eagerly: alternatives can contain cycles
        # or references that are irrelevant to the selected implementation.
        return {
            name: RelationshipView(relationship, self)
            for name, relationship in self.definition.relationships.items()
        }


@dataclass(eq=False)
class RelationshipView:
    definition: Relationship
    _parent: ModelView

    @property
    def constraints(self):
        return self.definition.constraints

    @property
    def connections(self):
        return self.definition.connections

    @property
    def derivatives(self):
        return self.definition.derivatives

    @cached_property
    def models(self) -> dict[str, ModelView]:
        parent = self._parent
        children = {
            alias: parent._library._reference(
                reference, parent.model_arguments, f"{parent.path}.{alias}"
            )
            for alias, reference in self.definition.models.items()
        }
        for child in children.values():
            for local, source in child.domain_bindings.items():
                if (
                    local not in child.definition.domains
                    or source not in parent.definition.domains
                    or child.definition.domains[local].kind
                    != parent.definition.domains[source].kind
                ):
                    raise ValueError(f"{child.path}: invalid domain binding {local!r}: {source!r}")
            for name, domain in child.definition.domains.items():
                if domain.kind == "time" and name not in child.domain_bindings:
                    raise ValueError(f"{child.path}: time domain {name!r} requires an explicit binding")
        return children
