"""Load and navigate definition references without constructing solver objects."""

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import pint

from .definitions import (
    Model,
    ModelParameter,
    ModelReference,
    ParameterModelReference,
    Relationship,
)


# Unit compatibility is a property of definitions, not of the Pyomo backend.
_UNITS = pint.UnitRegistry()


def _check_interface(definition: Model, requirement: ModelParameter, path: str):
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
        self.models: dict[str, Model] = {}
        for path in sorted(directory.glob("*.json")):
            document = Model.model_validate_json(path.read_text())
            if document.id in self.models:
                raise ValueError(f"Duplicate model ID: {document.id}")
            self.models[document.id] = document

    def get(self, name: str) -> Model:
        try:
            return self.models[name]
        except KeyError:
            raise ValueError(f"Unknown model: {name}") from None

    def resolve(self, name: str) -> "ResolvedModel":
        """Open a concrete root; resolve descendants automatically as accessed.

        Each call creates a fresh navigation view. Treat definitions as unchanged
        while using that view; open a new view after editing library documents.
        """
        definition = self.get(name)
        if definition.model_parameters:
            raise ValueError(
                "Root generic models are not supported; use a concrete wrapper"
            )
        return ResolvedModel(definition, {}, self, name)

    def _reference(
        self, reference: ModelReference, parameters, path: str
    ) -> "ResolvedModel":
        if isinstance(reference, ParameterModelReference):
            name = reference.model_parameter
            if name not in parameters:
                raise ValueError(f"{path}: unknown model parameter {name!r}")
            argument = parameters[name]
            return ResolvedModel(
                argument.definition, argument.model_arguments, self, path
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
        return ResolvedModel(definition, arguments, self, path)


@dataclass(eq=False)
class ResolvedModel:
    """A shared definition viewed in one generic-argument and reference context."""

    definition: Model
    model_arguments: dict[str, "ResolvedModel"]
    _library: Library
    path: str

    @property
    def id(self):
        return self.definition.id

    @property
    def structs(self):
        return self.definition.structs

    @cached_property
    def relationships(self) -> dict[str, "ResolvedRelationship"]:
        # Do not traverse descendants eagerly: alternatives can contain cycles
        # or references that are irrelevant to the selected implementation.
        return {
            name: ResolvedRelationship(relationship, self)
            for name, relationship in self.definition.relationships.items()
        }


@dataclass(eq=False)
class ResolvedRelationship:
    definition: Relationship
    _parent: ResolvedModel

    @property
    def constraints(self):
        return self.definition.constraints

    @property
    def connections(self):
        return self.definition.connections

    @cached_property
    def models(self) -> dict[str, ResolvedModel]:
        parent = self._parent
        return {
            alias: parent._library._reference(
                reference, parent.model_arguments, f"{parent.path}.{alias}"
            )
            for alias, reference in self.definition.models.items()
        }
