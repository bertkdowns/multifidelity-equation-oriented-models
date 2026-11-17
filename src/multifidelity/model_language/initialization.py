"""Starting guesses and explicit custom initialisation; no parameter choices."""

from copy import deepcopy
import math
from pathlib import Path

from .resources import ResourceCatalog
from .parameters import ParameterCatalog


def apply_starting_values(model, resources: ResourceCatalog, parameters=None,
                          *, excluded_record_tags=()):
    """Seed free public entries from unused resources, without fixing them.

    Highest trust wins (tag breaks ties). Unknown paths belong to other selected
    modelCatalogs and are ignored. Explicit exclusions support held-out data.
    Selected parameters/initial-condition records are excluded. Validate all
    applicable guesses before writing; return the IDs actually used.
    """
    from pyomo.environ import units
    from .builder import _expression

    registry = getattr(model, '_model_language_variables', None)
    if registry is None:
        raise ValueError('Model must be constructed by model_language.build_model')
    if not isinstance(resources, ResourceCatalog):
        raise TypeError('resources must be an ResourceCatalog')
    excluded = set(excluded_record_tags)
    if parameters is not None:
        if isinstance(parameters, (str, Path)):
            parameters = ParameterCatalog.load_json(parameters)
        elif not isinstance(parameters, ParameterCatalog):
            parameters = ParameterCatalog.model_validate(parameters)
        excluded.update(parameters.parameters + parameters.initial_values)
    prepared, used = [], []
    for path, component in registry.items():
        if all(v.fixed for v in component.values()):
            continue
        candidates = [r for r in resources.candidates(path) if r.tag not in excluded]
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
            used.append(record.tag)
        except Exception as error:
            raise ValueError(f'{path} ({record.tag}): {error}') from error
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
    parameters are transferred in native units first. Free public values
    are refreshed from native results afterwards. Callback fixes and constraint
    activation changes are restored; failure also restores starting values.
    This is a provider hook runner; initialize_model orchestrates recursive DM
    initialisation and parent solves separately.
    """
    from pyomo.environ import Block, Constraint, Var, units
    if hasattr(model, '_model_language_variables'):
        from .replacement import audit_fixations
        audit_fixations(model)

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
            # A callback must not change a pre-existing native parameters.
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
