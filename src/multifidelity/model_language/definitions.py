"""Typed definition documents, independent of reference resolution and Pyomo.

These types mirror the JSON vocabulary. Model references retain IDs rather than
expanding reusable definitions into a tree. Parsing checks document shape; the
builder still owns scope, interface, determination and equation validation.
"""

from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
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


class Bounds(Definition):
    min: float | None = None
    max: float | None = None


class Domain(Definition):
    """An index-domain declaration; numerical members belong to the build."""

    kind: Literal["time", "discrete"] = "discrete"


class Variable(Definition):
    """Quantity metadata; values and fixation belong to future instance types."""

    unit: str = "dimensionless"
    value_type: Literal["real"] = "real"
    bounds: Bounds = Field(default_factory=Bounds)
    dimensions: list[Name] = Field(default_factory=list)

    @model_validator(mode="after")
    def distinct_dimensions(self):
        if len(set(self.dimensions)) != len(self.dimensions):
            raise ValueError("Variable dimensions must be distinct")
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


class ModelParameter(Definition):
    """Minimum public struct interface required of a generic argument."""

    requires: dict[Name, Struct] = Field(default_factory=dict)


class ConcreteModelReference(Definition):
    model: str
    model_arguments: dict[Name, "ModelReference"] = Field(default_factory=dict)
    domain_bindings: dict[Name, Name] = Field(default_factory=dict)


class ParameterModelReference(Definition):
    model_parameter: str
    domain_bindings: dict[Name, Name] = Field(default_factory=dict)


# Separate variants enforce exactly one reference kind. Parameter references
# cannot override arguments that were already supplied by the containing model.
type ModelReference = ConcreteModelReference | ParameterModelReference


class ExternalRelationship(Definition):
    """A registered symbolic provider and its authored public dependencies."""

    provider: str = Field(min_length=1)
    config: dict[str, JsonValue] = Field(default_factory=dict)
    dependencies: dict[str, list[str]]


class Relationship(Definition):
    models: dict[Name, ModelReference] = Field(default_factory=dict)
    constraints: dict[Name, Constraint] = Field(default_factory=dict)
    connections: dict[Name, Connection] = Field(default_factory=dict)
    derivatives: dict[Name, Derivative] = Field(default_factory=dict)
    external: ExternalRelationship | None = None

    @model_validator(mode="after")
    def separate_external_implementation(self):
        if self.external is not None and (
            self.models or self.constraints or self.connections or self.derivatives
        ):
            raise ValueError(
                "An external relationship cannot also define models, constraints, connections, or derivatives; use a JSON wrapper"
            )
        return self


class Model(Definition):
    id: str
    description: str | None = None
    domains: dict[Name, Domain] = Field(default_factory=dict)
    model_parameters: dict[Name, ModelParameter] = Field(default_factory=dict)
    structs: dict[Name, Struct]
    relationships: dict[Name, Relationship]


ConcreteModelReference.model_rebuild()
Relationship.model_rebuild()
Model.model_rebuild()
