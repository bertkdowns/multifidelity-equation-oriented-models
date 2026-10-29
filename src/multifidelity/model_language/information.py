"""Information records and candidate lookup, without specification decisions."""

from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


type InformationType = Literal[
    "sensor_reading",
    "control_setpoint",
    "equipment_specification",
    "parameter",
    "assumption",
]


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
    value: float
    unit: str = Field(min_length=1)
    standard_deviation: float | None = Field(default=None, ge=0)
    trust_rank: int = Field(ge=1, le=10, strict=True)


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
