"""Portable parameter choices, separate from evidence and numerical objects."""

import math
from pathlib import Path
from typing import Annotated

from pydantic import ConfigDict, Field, model_validator

from .definitions import Definition
from .resources import ResourceCatalog
from .variables import get_variable


class ParameterCatalog(Definition):
    """Only parameter choices; context and diagnostics are supplied separately."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    parameters: tuple[Annotated[str, Field(min_length=1)], ...] = ()
    replacements: dict[Annotated[str, Field(min_length=1)], Annotated[str, Field(min_length=1)]] = Field(default_factory=dict)
    initial_values: tuple[Annotated[str, Field(min_length=1)], ...] = ()

    @model_validator(mode="after")
    def unique_records(self):
        tags = self.parameters + self.initial_values
        if len(tags) != len(set(tags)):
            raise ValueError("Each resource record may be selected only once across both lists")
        if set(self.replacements) - set(self.parameters):
            raise ValueError("Replacement keys must name selected operating parameter resources")
        if len(set(self.replacements.values())) != len(self.replacements):
            raise ValueError("Each canonical input can be replaced only once")
        return self


def _catalog(parameters):
    if isinstance(parameters, (str, Path)):
        return ParameterCatalog.load_json(parameters)
    if not isinstance(parameters, ParameterCatalog):
        return ParameterCatalog.model_validate(parameters)
    # Revalidate editable nested mappings and model_copy(update=...) catalogs.
    return ParameterCatalog.model_validate(parameters.model_dump())


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


def _prepare(model, parameters, resources):
    # Keep catalog parsing independent of the optional numerical backend.
    from pyomo.environ import units
    from .builder import _expression

    parameters = _catalog(parameters)
    if not isinstance(resources, ResourceCatalog):
        raise TypeError("resources must be an ResourceCatalog")
    registry = getattr(model, "_model_language_variables", None)
    if registry is None:
        raise ValueError("Model must be constructed by model_language.build_model")

    prepared = []
    seen_paths = set()
    selected = [(record_tag, False) for record_tag in parameters.parameters]
    selected += [(record_tag, True) for record_tag in parameters.initial_values]
    for record_tag, initial in selected:
        try:
            record = resources.get(record_tag)
        except KeyError as error:
            raise ValueError(str(error)) from error
        path = record.variable_path
        if path in seen_paths:
            raise ValueError(f"Multiple resource records specify variable {path!r}")
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
            raise ValueError(f"{path} ({record.tag}): {error}") from error
    return prepared


def apply_parameters(model, parameters, resources) -> None:
    """Apply direct input fixes or explicitly paired operating replacements.

    Validation failure leaves values and fixed/free statuses unchanged. The
    resources catalog is read only. No solver or initialization is invoked.
    Reapplying to already fixed variables is an error, including equal values.
    Initial values require dynamic time-indexed variables. Constants broadcast
    over non-time axes; series give initial profiles in non-time dimension order.
    """
    from .replacement import _validate_slots, audit_fixations
    parameters = _catalog(parameters)
    prepared = _prepare(model, parameters, resources)
    audit_fixations(model)
    slots = _validate_slots(model, parameters, resources)
    initial_entries = set()
    for record_tag in parameters.initial_values:
        record = resources.get(record_tag)
        family = get_variable(model, record.variable_path)
        initial_entries.update((record.variable_path, index)
                               for index in _initial_values_for(record, family, model))
    initial_paths = {path for path, _ in initial_entries}
    for slot, entry in {**model._model_language_parameter_slots, **slots}.items():
        if slot != entry['variable_path'] and slot in initial_paths:
            raise ValueError(f'{slot}: replaced canonical input must remain free, including its initial slice')
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
    model._model_language_parameter_slots.update(slots)
    model._model_language_initial_fixations.update(initial_entries)
