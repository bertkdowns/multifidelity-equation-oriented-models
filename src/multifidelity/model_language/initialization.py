"""Starting guesses and explicit custom initialisation; no specification choices."""

from copy import deepcopy
import math
from pathlib import Path

from .information import InformationDocument
from .specification import SpecificationDocument


def apply_starting_values(model, information: InformationDocument, specification=None,
                          *, excluded_record_ids=()):
    """Seed free public entries from unused information, without fixing them.

    Highest trust wins (ID breaks ties). Unknown paths belong to other selected
    implementations and are ignored. Explicit exclusions support held-out data.
    Selected specification/initial-condition records are excluded. Validate all
    applicable guesses before writing; return the IDs actually used.
    """
    from pyomo.environ import units
    from .builder import _expression

    registry = getattr(model, '_model_language_variables', None)
    if registry is None:
        raise ValueError('Model must be constructed by model_language.build_model')
    if not isinstance(information, InformationDocument):
        raise TypeError('information must be an InformationDocument')
    excluded = set(excluded_record_ids)
    if specification is not None:
        if isinstance(specification, (str, Path)):
            specification = SpecificationDocument.load_json(specification)
        elif not isinstance(specification, SpecificationDocument):
            specification = SpecificationDocument.model_validate(specification)
        excluded.update(specification.specifications + specification.initial_values)
    prepared, used = [], []
    for path, component in registry.items():
        if all(v.fixed for v in component.values()):
            continue
        candidates = [r for r in information.candidates(path) if r.id not in excluded]
        if not candidates:
            continue
        record = candidates[0]
        try:
            source = _expression(record.unit, lambda name: getattr(units, name))
            for index, original in record.values_for(component).items():
                variable = component[index]
                if variable.fixed:
                    continue
                converted = units.convert_value(original, from_units=source,
                                                to_units=units.get_units(variable))
                if not math.isfinite(converted) or (
                    variable.lb is not None and converted < variable.lb
                ) or (variable.ub is not None and converted > variable.ub):
                    raise ValueError('starting value must be finite and within bounds')
                prepared.append((variable, converted))
            used.append(record.id)
        except Exception as error:
            raise ValueError(f'{path} ({record.id}): {error}') from error
    previous = [(v, v.value) for v, _ in prepared]
    try:
        for variable, guess in prepared:
            variable.set_value(guess)
    except Exception:
        for variable, old in previous:
            variable.set_value(old, skip_validation=True)
        raise
    return used


def initialize_custom_models(model):
    """Run registered callbacks on constructed provider slices, in tree order.

    Callbacks receive (native_block, config). Public input guesses and fixed
    specifications are transferred in native units first. Free public values
    are refreshed from native results afterwards. Callback fixes and constraint
    activation changes are restored; failure also restores starting values.
    This is a provider hook runner; initialize_model orchestrates recursive DM
    initialisation and parent solves separately.
    """
    from pyomo.environ import Block, Constraint, Var, units

    def transfer(source, target):
        if source.value is not None:
            target.set_value(units.convert_value(
                source.value, from_units=units.get_units(source),
                to_units=units.get_units(target)))

    completed = []
    for active in [model, *model.component_data_objects(Block, descend_into=True)]:
        metadata = getattr(active, '_model_language_initialization', None)
        if metadata is None or metadata[0] is None:
            continue
        callback, config, public, native, outputs = metadata
        variables = {id(v): v for v in active.component_data_objects(Var)}
        variables.update({id(v): v for v in public.values()})
        old = [(v, v.value, v.fixed) for v in variables.values()]
        constraints = [(c, c.active) for c in active.component_data_objects(
            Constraint, active=None)]
        success = False
        try:
            for name, variable in public.items():
                if variable.fixed or (name not in outputs and not native[name].fixed):
                    transfer(variable, native[name])
                if variable.fixed:
                    native[name].fix()
            callback(active.provider, deepcopy(config))
            # A callback must not change a pre-existing native specification.
            # Restore these values before exposing its results to public ports.
            for variable, guess, fixed in old:
                if fixed:
                    variable.set_value(guess, skip_validation=True)
            for name, variable in public.items():
                if not variable.fixed:
                    transfer(native[name], variable)
            success = True
            completed.append(active.name)
        finally:
            for variable, guess, fixed in old:
                if fixed or not success:
                    variable.set_value(guess, skip_validation=True)
                variable.fixed = fixed
            for constraint, enabled in constraints:
                constraint.activate() if enabled else constraint.deactivate()
    return completed
