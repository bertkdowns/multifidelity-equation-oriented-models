"""Load and navigate definition references without constructing solver objects."""

from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import pint

from .definitions import (
    BlockCatalog,
    BlockSlot,
    BlockReference,
    SlotBlockReference,
    Formulation,
)
from .providers import Initializer, SymbolicProvider, Scaler


# Unit compatibility is a property of definitions, not of the Pyomo backend.
_UNITS = pint.UnitRegistry()


def _check_interface(definition: BlockCatalog, requirement: BlockSlot, path: str):
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


class BlockLibrary:
    """An ID-indexed library of typed catalogs with resolved navigation views."""

    def __init__(self, directory=None):
        directory = Path(directory) if directory else Path(__file__).parent / "blocks"
        self.blocks: dict[str, BlockCatalog] = {}
        self._providers: dict[str, SymbolicProvider] = {}
        self._initializers: dict[str, Initializer] = {}
        self._scalers: dict[str, Scaler] = {}
        for path in sorted(directory.glob("*.json")):
            catalog = BlockCatalog.load_json(path)
            if catalog.id in self.blocks:
                raise ValueError(f"Duplicate model ID: {catalog.id}")
            self.blocks[catalog.id] = catalog

    def register_provider(self, name: str, provider: SymbolicProvider, *,
                          initializer: Initializer | None = None,
                          scaler: Scaler | None = None) -> None:
        """Register trusted Python code; definitions only store its stable name."""
        if name in self._providers:
            raise ValueError(f"Duplicate provider: {name}")
        self._providers[name] = provider
        if initializer is not None:
            self._initializers[name] = initializer
        if scaler is not None:
            self._scalers[name] = scaler

    def get_scaler(self, name: str) -> Scaler | None:
        return self._scalers.get(name)

    def get_initializer(self, name: str) -> Initializer | None:
        """Optional numerical callback, separate from symbolic construction."""
        return self._initializers.get(name)

    def get_provider(self, name: str) -> SymbolicProvider:
        """Resolve a provider only when its external formulation is built."""
        try:
            return self._providers[name]
        except KeyError:
            raise ValueError(f"Unknown provider: {name}") from None

    def get(self, name: str) -> BlockCatalog:
        try:
            return self.blocks[name]
        except KeyError:
            raise ValueError(f"Unknown model: {name}") from None

    def resolve(self, name: str) -> "BlockView":
        """Open a concrete root; resolve descendants automatically as accessed.

        Each call creates a fresh navigation view. Treat definitions as unchanged
        while using that view; open a new view after editing library catalogs.
        """
        definition = self.get(name)
        if definition.block_slots:
            raise ValueError(
                "Root generic blocks are not supported; use a concrete wrapper"
            )
        return BlockView(definition, {}, self, name)

    def _reference(
        self, reference: BlockReference, parameters, path: str
    ) -> "BlockView":
        if isinstance(reference, SlotBlockReference):
            name = reference.block_slot
            if name not in parameters:
                raise ValueError(f"{path}: unknown block slot {name!r}")
            argument = parameters[name]
            return BlockView(
                argument.definition, argument.block_arguments, self, path,
                dict(reference.domain_bindings),
            )
        definition = self.get(reference.block)
        declarations = definition.block_slots
        if set(reference.block_arguments) != set(declarations):
            raise ValueError(
                f"{path}: block arguments must be exactly {sorted(declarations)}"
            )
        arguments = {}
        for name, requirement in declarations.items():
            argument = self._reference(
                reference.block_arguments[name], parameters, f"{path}<{name}>"
            )
            _check_interface(argument.definition, requirement, f"{path}<{name}>")
            arguments[name] = argument
        return BlockView(definition, arguments, self, path, dict(reference.domain_bindings))


@dataclass(eq=False)
class BlockView:
    """A shared definition viewed in one generic-argument and reference context."""

    definition: BlockCatalog
    block_arguments: dict[str, "BlockView"]
    _library: BlockLibrary
    path: str
    domain_bindings: dict[str, str] = field(default_factory=dict)

    @property
    def id(self):
        return self.definition.id

    @property
    def structs(self):
        return self.definition.structs

    @cached_property
    def formulations(self) -> dict[str, "FormulationView"]:
        # Do not traverse descendants eagerly: alternatives can contain cycles
        # or references that are irrelevant to the selected model.
        return {
            name: FormulationView(formulation, self)
            for name, formulation in self.definition.formulations.items()
        }


@dataclass(eq=False)
class FormulationView:
    definition: Formulation
    _parent: BlockView

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
    def blocks(self) -> dict[str, BlockView]:
        parent = self._parent
        children = {
            alias: parent._library._reference(
                reference, parent.block_arguments, f"{parent.path}.{alias}"
            )
            for alias, reference in self.definition.blocks.items()
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
