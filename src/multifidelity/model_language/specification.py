"""Portable specification choices, separate from evidence and numerical objects."""

import math
from pathlib import Path
from typing import Annotated

from pydantic import ConfigDict, Field, model_validator

from .definitions import Definition
from .information import InformationDocument
from .variables import get_variable


class SpecificationDocument(Definition):
    """Only specification choices; context and diagnostics are supplied separately."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    specifications: tuple[Annotated[str, Field(min_length=1)], ...] = ()
    initial_values: tuple[Annotated[str, Field(min_length=1)], ...] = ()

    @model_validator(mode="after")
    def unique_records(self):
        ids = self.specifications + self.initial_values
        if len(ids) != len(set(ids)):
            raise ValueError("Each information record may be selected only once across both lists")
        return self


def _initial_values_for(record, component, model):
    """Map a record to the first time point, retaining all other index axes."""
    if not model.fs.config.dynamic:
        raise ValueError("Initial values apply only in dynamic mode")
    domains = list(component.index_set().subsets()) if component.is_indexed() else []
    time_axes = [axis for axis, domain in enumerate(domains) if domain is model.fs.time]
    if len(time_axes) != 1:
        raise ValueError("Initial values require a time-indexed variable")
    time_axis = time_axes[0]
    remaining = domains[:time_axis] + domains[time_axis + 1:]
    values = record._values_for_domains(remaining)
    result = {}
    for key, value in values.items():
        index = [] if not remaining else list(key if len(remaining) > 1 else (key,))
        index.insert(time_axis, model.fs.time.first())
        full_key = index[0] if len(index) == 1 else tuple(index)
        result[full_key] = value
    return result


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
    seen_paths = set()
    selected = [(record_id, False) for record_id in specification.specifications]
    selected += [(record_id, True) for record_id in specification.initial_values]
    for record_id, initial in selected:
        try:
            record = information.get(record_id)
        except KeyError as error:
            raise ValueError(str(error)) from error
        path = record.variable_path
        if path in seen_paths:
            raise ValueError(f"Multiple information records specify variable {path!r}")
        seen_paths.add(path)
        component = get_variable(model, path)
        try:
            source_unit = _expression(record.unit, lambda name: getattr(units, name))
            target_unit = units.get_units(component)
            values = (_initial_values_for(record, component, model) if initial
                      else record.values_for(component))
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
    """Validate both lists, then fix whole families or initial time slices.

    Validation failure leaves values and fixed/free statuses unchanged. The
    information document is read only. No solver or initialization is invoked.
    Reapplying to already fixed variables is an error, including equal values.
    Initial values require dynamic time-indexed variables. Constants broadcast
    over non-time axes; series give initial profiles in non-time dimension order.
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
