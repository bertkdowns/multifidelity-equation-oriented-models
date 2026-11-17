"""Typed block definitions, independent of reference resolution and Pyomo.

These types mirror the JSON vocabulary. BlockDefinition references retain IDs rather than
expanding reusable definitions into a tree. Parsing checks definition shape; the
builder still owns scope, interface, determination and equation validation.
"""

from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    FiniteFloat,
    model_validator,
)


def _identifier(value: str) -> str:
    """Names must support dotted references and avoid private component names."""
    if not value.isidentifier() or value.startswith("_"):
        raise ValueError(f"Invalid identifier: {value!r}")
    return value


type Name = Annotated[str, AfterValidator(_identifier)]


class Definition(BaseModel):
    """Reject misspelled fields rather than silently discarding definition data."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @classmethod
    def from_json(cls, text: str | bytes) -> Self:
        return cls.model_validate_json(text)

    @classmethod
    def load_json(cls, path: str | Path) -> Self:
        return cls.from_json(Path(path).read_text(encoding="utf-8"))


class Bounds(Definition):
    min: float | None = None
    max: float | None = None


class Domain(Definition):
    """An index-domain declaration; numerical members belong to the build."""

    kind: Literal["time", "discrete"] = "discrete"


class Variable(Definition):
    """Quantity metadata and an optional unfixed guess in the declared unit."""

    unit: str = "dimensionless"
    value_type: Literal["real"] = "real"
    bounds: Bounds = Field(default_factory=Bounds)
    dimensions: list[Name] = Field(default_factory=list)
    default: FiniteFloat | None = None
    scale: FiniteFloat | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def distinct_dimensions(self):
        if len(set(self.dimensions)) != len(self.dimensions):
            raise ValueError("Variable dimensions must be distinct")
        if self.default is not None and (
            (self.bounds.min is not None and self.default < self.bounds.min)
            or (self.bounds.max is not None and self.default > self.bounds.max)
        ):
            raise ValueError("Variable default must be within bounds")
        return self


class Struct(Definition):
    direction: Literal["input", "output"]
    variables: dict[Name, Variable]


class Constraint(Definition):
    for_each: dict[Name, Name] = Field(default_factory=dict)
    lhs: str
    rhs: str
    determines: str


class Derivative(Definition):
    """First-order relation between two local variable families."""

    kind: Literal["derivative"] = "derivative"
    state: str
    rate: str
    with_respect_to: Name
    determines: str


class Connection(Definition):
    # Python reserves `from`; serialization preserves the original JSON spelling.
    from_: str = Field(alias="from")
    to: str


class BlockArgument(Definition):
    """A named generic block argument with a required public struct interface."""

    requires: dict[Name, Struct] = Field(default_factory=dict)


class ConcreteBlockReference(Definition):
    block: str
    block_arguments: dict[Name, "BlockReference"] = Field(default_factory=dict)
    domain_bindings: dict[Name, Name] = Field(default_factory=dict)


class ArgumentBlockReference(Definition):
    block_argument: str
    domain_bindings: dict[Name, Name] = Field(default_factory=dict)


# Separate variants enforce exactly one reference kind. Argument references
# cannot override arguments that were already supplied by the containing model.
type BlockReference = ConcreteBlockReference | ArgumentBlockReference


class ExternalFormulation(Definition):
    """A registered symbolic provider and its authored public dependencies."""

    provider: str = Field(min_length=1)
    config: dict[str, JsonValue] = Field(default_factory=dict)
    dependencies: dict[str, list[str]]


class Formulation(Definition):
    blocks: dict[Name, BlockReference] = Field(default_factory=dict)
    constraints: dict[Name, Constraint] = Field(default_factory=dict)
    connections: dict[Name, Connection] = Field(default_factory=dict)
    derivatives: dict[Name, Derivative] = Field(default_factory=dict)
    external: ExternalFormulation | None = None

    @model_validator(mode="after")
    def separate_external_model_document(self):
        if self.external is not None and (
            self.blocks or self.constraints or self.connections or self.derivatives
        ):
            raise ValueError(
                "An external formulation cannot also define blocks, constraints, connections, or derivatives; use a JSON wrapper"
            )
        return self


class BlockDefinition(Definition):
    id: str
    description: str | None = None
    domains: dict[Name, Domain] = Field(default_factory=dict)
    block_arguments: dict[Name, BlockArgument] = Field(default_factory=dict)
    structs: dict[Name, Struct]
    formulations: dict[Name, Formulation]


ConcreteBlockReference.model_rebuild()
Formulation.model_rebuild()
BlockDefinition.model_rebuild()
