"""Information records and candidate lookup, without specification decisions."""

from collections.abc import Iterable
from itertools import product
from numbers import Integral, Real
from pathlib import Path
from typing import Annotated, Literal, TYPE_CHECKING, cast

from pydantic import (
    BaseModel, BeforeValidator, ConfigDict, Field, FiniteFloat, TypeAdapter,
    model_validator,
)

if TYPE_CHECKING:
    from pyomo.core.base.var import Var


type InformationType = Literal[
    "sensor_reading",
    "control_setpoint",
    "equipment_specification",
    "parameter",
    "assumption",
]


type InformationValue = FiniteFloat | tuple[InformationValue, ...]


def _normalize_value(value):
    # NumPy arrays/scalars expose tolist(); no NumPy import is needed to load
    # information records. Copy containers so frozen records stay immutable.
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
    raise ValueError("Information values must be real numbers or numeric arrays")


def _value_shape(value):
    if not isinstance(value, tuple):
        return ()
    if not value:
        raise ValueError("Series arrays must be nonempty")
    shape = _value_shape(value[0])
    if any(_value_shape(item) != shape for item in value[1:]):
        raise ValueError("Series arrays must be rectangular")
    return (len(value), *shape)


class InformationRecord(BaseModel):
    """One observation or specification; uncertainty is in the value's unit.

    Records are immutable so IDs cannot change after insertion into a table.
    Missing uncertainty means unknown; zero explicitly means treated as exact.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    id: str = Field(min_length=1)
    tag: str = Field(min_length=1)
    information_type: InformationType
    variable_path: str = Field(min_length=1)
    type: Literal["constant", "series"] = "constant"
    value: Annotated[InformationValue, BeforeValidator(_normalize_value)]
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
                f"{self.id}: series shape {self.shape} does not match variable shape {shape}"
            )

    def values_for(self, variable: "Var") -> dict[object, float]:
        """Map record values to a Pyomo variable's current grid, without fixing it.

        Constants broadcast. Series follow ordered domain products, in declared
        dimension order. Values remain in the record's unit; this operation
        neither checks physical applicability nor converts units.
        """
        if not variable.is_indexed():
            self.validate_shape(())
            return {None: cast(float, self.value)}
        if self.type == "constant":
            return {key: cast(float, self.value) for key in variable.index_set()}
        domains = list(variable.index_set().subsets())
        if any(not domain.isordered() or domain.dimen != 1 for domain in domains):
            raise ValueError("Information arrays require ordered one-dimensional index domains")
        self.validate_shape(len(domain) for domain in domains)

        def entries(value):
            if isinstance(value, tuple):
                for item in value:
                    yield from entries(item)
            else:
                yield value

        keys = (index[0] if len(index) == 1 else index for index in product(*domains))
        return dict(zip(keys, entries(self.value), strict=True))


_RECORDS = TypeAdapter(list[InformationRecord])


class InformationTable:
    """Records for one operating case, preserving alternatives for each variable.

    Paths and units remain declarations here. The specification algorithm checks
    applicability to a selected model; this table never fixes or combines values.
    """

    def __init__(self, records: Iterable[InformationRecord | dict] = ()):
        self._records: dict[str, InformationRecord] = {}
        for record in records:
            self.add(record)

    @classmethod
    def from_json(cls, text: str | bytes) -> "InformationTable":
        """Create a table from a JSON array, rejecting invalid or duplicate records."""
        return cls(_RECORDS.validate_json(text))

    @classmethod
    def load_json(cls, path: str | Path) -> "InformationTable":
        """Load a JSON array of records from a UTF-8 file."""
        return cls.from_json(Path(path).read_text(encoding="utf-8"))

    @property
    def records(self) -> list[InformationRecord]:
        """Return records in insertion order without exposing mutable storage."""
        return list(self._records.values())

    def add(self, record: InformationRecord | dict) -> InformationRecord:
        """Validate and insert one record; never overwrite an existing ID."""
        record = InformationRecord.model_validate(record)
        if record.id in self._records:
            raise ValueError(f"Duplicate information record ID: {record.id}")
        self._records[record.id] = record
        return record

    def get(self, record_id: str) -> InformationRecord:
        try:
            return self._records[record_id]
        except KeyError:
            raise KeyError(f"Unknown information record: {record_id}") from None

    def candidates(self, variable_path: str) -> list[InformationRecord]:
        """Return all alternatives, highest trust first, then record ID for ties."""
        return sorted(
            (
                record
                for record in self._records.values()
                if record.variable_path == variable_path
            ),
            key=lambda record: (-record.trust_rank, record.id),
        )
