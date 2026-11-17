"""Resource records and candidate lookup, without parameter decisions."""

from collections.abc import Iterable
from itertools import product
from numbers import Integral, Real
from pathlib import Path
from typing import Annotated, Literal, TYPE_CHECKING, cast

from pydantic import (
    BaseModel, BeforeValidator, ConfigDict, Field, FiniteFloat, RootModel, field_validator,
    model_validator,
)

if TYPE_CHECKING:
    from pyomo.core.base.var import Var


type ResourceType = Literal[
    "sensor_reading",
    "control_setpoint",
    "equipment_parameter",
    "parameter",
    "assumption",
]


type ResourceValue = FiniteFloat | tuple[ResourceValue, ...]


def _normalize_value(value):
    # NumPy arrays/scalars expose tolist(); no NumPy import is needed to load
    # resource records. Copy containers so frozen records stay immutable.
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        value = tolist()
    if isinstance(value, (list, tuple)):
        return tuple(_normalize_value(item) for item in value)
    if isinstance(value, Real) and not isinstance(value, bool):
        try:
            return float(value)
        except OverflowError:
            pass
    raise ValueError("Resource values must be real numbers or numeric arrays")


def _value_shape(value):
    if not isinstance(value, tuple):
        return ()
    if not value:
        raise ValueError("Series arrays must be nonempty")
    shape = _value_shape(value[0])
    if any(_value_shape(item) != shape for item in value[1:]):
        raise ValueError("Series arrays must be rectangular")
    return (len(value), *shape)


class Resource(BaseModel):
    """One observation or parameters; uncertainty is in the value's unit.

    Records are immutable so tags cannot change after insertion into a table.
    Missing uncertainty means unknown; zero explicitly means treated as exact.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    tag: str = Field(min_length=1)
    resource_type: ResourceType
    variable_path: str = Field(min_length=1)
    type: Literal["constant", "series"] = "constant"
    value: Annotated[ResourceValue, BeforeValidator(_normalize_value)]
    unit: str = Field(min_length=1)
    standard_deviation: float | None = Field(default=None, ge=0)
    trust_rank: int = Field(ge=1, le=10, strict=True)

    @model_validator(mode="after")
    def check_value_type(self):
        array = isinstance(self.value, tuple)
        if self.type == "constant" and array:
            raise ValueError("A constant record requires one numeric value")
        if self.type == "series" and not array:
            raise ValueError("A series record requires an array")
        _value_shape(self.value)
        return self

    @property
    def shape(self) -> tuple[int, ...]:
        """Array shape in variable dimension order; constants have shape ()."""
        return _value_shape(self.value)

    def validate_shape(self, shape: Iterable[int]) -> None:
        """Check a final grid shape without broadcasting or changing any values."""
        shape = tuple(shape)
        if any(isinstance(n, bool) or not isinstance(n, Integral) or n < 1 for n in shape):
            raise ValueError("Variable shape must contain positive integer sizes")
        if self.type == "series" and self.shape != shape:
            raise ValueError(
                f"{self.tag}: series shape {self.shape} does not match variable shape {shape}"
            )

    def values_for(self, variable: "Var") -> dict[object, float]:
        """Map record values to a Pyomo variable's current grid, without fixing it.

        Constants broadcast. Series follow ordered domain products, in declared
        dimension order. Values remain in the record's unit; this operation
        neither checks physical applicability nor converts units.
        """
        if self.type == "constant":
            keys = variable.index_set() if variable.is_indexed() else [None]
            return {key: cast(float, self.value) for key in keys}
        domains = list(variable.index_set().subsets()) if variable.is_indexed() else []
        return self._values_for_domains(domains)

    def _values_for_domains(self, domains):
        """Map values over full domains or a caller-selected initial slice."""
        if any(not domain.isordered() or domain.dimen != 1 for domain in domains):
            if self.type == "series":
                raise ValueError("Resource arrays require ordered one-dimensional index domains")
        self.validate_shape(len(domain) for domain in domains)
        if self.type == "constant":
            return {
                (None if not index else index[0] if len(index) == 1 else index): cast(float, self.value)
                for index in product(*domains)
            }

        def entries(value):
            if isinstance(value, tuple):
                for item in value:
                    yield from entries(item)
            else:
                yield value

        keys = (None if not index else index[0] if len(index) == 1 else index
                for index in product(*domains))
        return dict(zip(keys, entries(self.value), strict=True))


class ResourceDocument(RootModel[tuple[Resource, ...]]):
    """Pydantic array document retaining alternative records for one case.

    Serialization uses the same JSON array as loading. Records and the root tuple
    cannot be mutated in place; add() validates a replacement tuple atomically.
    """

    model_config = ConfigDict(validate_assignment=True)
    root: tuple[Resource, ...] = ()

    @field_validator("root")
    @classmethod
    def unique_tags(cls, records):
        tags = [record.tag for record in records]
        if len(tags) != len(set(tags)):
            raise ValueError("Duplicate resource record tag")
        return records

    @classmethod
    def from_json(cls, text: str | bytes) -> "ResourceDocument":
        return cls.model_validate_json(text)

    @classmethod
    def load_json(cls, path: str | Path) -> "ResourceDocument":
        return cls.from_json(Path(path).read_text(encoding="utf-8"))

    @property
    def records(self) -> list[Resource]:
        return list(self.root)

    def add(self, record: Resource | dict) -> Resource:
        record = Resource.model_validate(record)
        self.root = (*self.root, record)
        return record

    def get(self, record_tag: str) -> Resource:
        for record in self.root:
            if record.tag == record_tag:
                return record
        raise KeyError(f"Unknown resource record: {record_tag}")

    def candidates(self, variable_path: str) -> list[Resource]:
        return sorted(
            (record for record in self.root if record.variable_path == variable_path),
            key=lambda record: (-record.trust_rank, record.tag),
        )
