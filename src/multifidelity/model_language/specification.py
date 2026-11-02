"""Portable specification choices, separate from evidence and numerical objects."""

import math
from pathlib import Path

from pydantic import ConfigDict, Field, model_validator

from .definitions import Definition
from .information import InformationDocument


class SpecificationEntry(Definition):
    """Fix a variable family using one information record's central values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    variable_path: str = Field(min_length=1)
    information_record_id: str = Field(min_length=1)


class SpecificationDocument(Definition):
    """Only specification choices; context and diagnostics are supplied separately."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    specifications: tuple[SpecificationEntry, ...]

    @model_validator(mode="after")
    def unique_variables(self):
        paths = [entry.variable_path for entry in self.specifications]
        if len(paths) != len(set(paths)):
            raise ValueError("Each variable path may be specified only once")
        return self

    @classmethod
    def from_json(cls, text: str | bytes) -> "SpecificationDocument":
        return cls.model_validate_json(text)

    @classmethod
    def load_json(cls, path: str | Path) -> "SpecificationDocument":
        return cls.from_json(Path(path).read_text(encoding="utf-8"))


def _prepare(model, specification, information):
    # Keep document parsing independent of the optional numerical backend.
    from pyomo.environ import units
    from .builder import _expression

    if isinstance(specification, (str, Path)):
        specification = SpecificationDocument.load_json(specification)
    elif not isinstance(specification, SpecificationDocument):
        specification = SpecificationDocument.model_validate(specification)
    if not isinstance(information, InformationDocument):
        raise TypeError("information must be an InformationDocument")
    registry = getattr(model, "_model_language_variables", None)
    if registry is None:
        raise ValueError("Model must be constructed by model_language.build_model")

    prepared = []
    for entry in specification.specifications:
        path = entry.variable_path
        if path not in registry:
            raise ValueError(f"Unknown specification variable {path!r}")
        try:
            record = information.get(entry.information_record_id)
        except KeyError as error:
            raise ValueError(str(error)) from error
        if record.variable_path != path:
            raise ValueError(f"{record.id}: information variable path does not match {path!r}")
        component = registry[path]
        try:
            source_unit = _expression(record.unit, lambda name: getattr(units, name))
            target_unit = units.get_units(component)
            values = record.values_for(component)
            if not values:
                raise ValueError("variable has no grid entries")
            for index, original in values.items():
                variable = component[index]
                converted = units.convert_value(
                    original, from_units=source_unit, to_units=target_unit,
                )
                if not math.isfinite(converted):
                    raise ValueError("converted value must be finite")
                if variable.fixed:
                    raise ValueError(f"entry {index!r} is already fixed")
                if ((variable.lb is not None and converted < variable.lb)
                        or (variable.ub is not None and converted > variable.ub)):
                    raise ValueError(f"entry {index!r} is outside variable bounds")
                prepared.append((variable, converted))
        except Exception as error:
            raise ValueError(f"{path} ({record.id}): {error}") from error
    return prepared


def apply_specification(model, specification, information) -> None:
    """Validate the entire document, then fix all selected entries.

    Validation failure leaves values and fixed/free statuses unchanged. The
    information document is read only. No solver or initialization is invoked.
    Reapplying to already fixed variables is an error, including equal values.
    """
    prepared = _prepare(model, specification, information)
    # Roll back unexpected backend failures as well as preventing partial writes
    # on ordinary validation errors.
    previous = [(variable, variable.value, variable.fixed) for variable, _ in prepared]
    try:
        for variable, converted in prepared:
            variable.fix(converted)
    except Exception:
        for variable, value, fixed in previous:
            variable.set_value(value, skip_validation=True)
            variable.fixed = fixed
        raise
