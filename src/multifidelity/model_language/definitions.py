"""Typed definition documents, independent of reference resolution and Pyomo.

These types mirror the JSON vocabulary. Model references retain IDs rather than
expanding reusable definitions into a tree. Parsing checks document shape; the
builder still owns scope, interface, determination and equation validation.
"""

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


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


class Variable(Definition):
    """Quantity metadata; values and fixation belong to future instance types."""

    unit: str = "dimensionless"
    value_type: Literal["real"] = "real"
    bounds: Bounds = Field(default_factory=Bounds)
    # Reserved for domain design; the scalar builder rejects nonempty dimensions.
    dimensions: list[str] = Field(default_factory=list)


class Struct(Definition):
    direction: Literal["input", "output"]
    variables: dict[Name, Variable]


class Constraint(Definition):
    lhs: str
    rhs: str
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


class ParameterModelReference(Definition):
    model_parameter: str


# Separate variants enforce exactly one reference kind. Parameter references
# cannot override arguments that were already supplied by the containing model.
type ModelReference = ConcreteModelReference | ParameterModelReference


class Relationship(Definition):
    models: dict[Name, ModelReference] = Field(default_factory=dict)
    constraints: dict[Name, Constraint] = Field(default_factory=dict)
    connections: dict[Name, Connection] = Field(default_factory=dict)


class Model(Definition):
    id: str
    description: str | None = None
    model_parameters: dict[Name, ModelParameter] = Field(default_factory=dict)
    structs: dict[Name, Struct]
    relationships: dict[Name, Relationship]


ConcreteModelReference.model_rebuild()
Relationship.model_rebuild()
Model.model_rebuild()
