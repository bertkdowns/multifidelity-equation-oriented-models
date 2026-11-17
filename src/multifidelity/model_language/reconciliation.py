"""Clone-based, weighted least-squares relaxation of selected parameters."""

from dataclasses import dataclass
import math
from numbers import Real

from .parameters import ParameterCatalog, _prepare, _catalog
from .scaling import _factor
from .replacement import audit_fixations


@dataclass
class ParameterRelaxation:
    model: object
    entries: list[dict]

    def deviations(self):
        """Rank signed changes in native units and weighted normalized magnitudes.

        These are diagnostics at the current values, not evidence of convergence.
        Check solver termination and physical equation residuals separately.
        """
        from pyomo.environ import value
        rows = []
        for entry in self.entries:
            row = {k: v for k, v in entry.items() if k != 'variable'}
            row['value'] = value(entry['variable'])
            row['deviation'] = row['value'] - row['target']
            row['scaled_deviation'] = row['deviation'] * row['scale']
            row['penalty'] = row['weight'] * row['scaled_deviation'] ** 2
            rows.append(row)
        return sorted(rows, key=lambda row: -row['penalty'])


def relax_parameters(model, parameters, resources, *, weights=None):
    """Return an independent diagnostic clone with resources fixes softened.

    Minimize sum(weight * (scale * (value - target))**2). Scales multiply native
    variable magnitudes, defaulting to 1. Weights are positive finite numbers keyed
    by record tag. All original equations and bounds remain hard; other fixed
    variables remain fixed. Existing objectives are deactivated on the clone.
    Selected parameters must already be applied at their recorded values.
    Neither source values/fixity nor resource records are changed. A nonzero
    optimum identifies joint reconciliation changes, not a unique faulty sensor.
    """
    from pyomo.environ import Block, Constraint, Objective, Var, units
    from idaes.core.util.scaling import set_scaling_factor
    parameters = _catalog(parameters)
    weights = dict(weights or {})
    selected = parameters.parameters + parameters.initial_values
    if not selected:
        raise ValueError('Select at least one parameters to relax')
    if set(weights) - set(selected):
        raise ValueError('Weights must refer to selected resource record tags')
    if any(isinstance(w, bool) or not isinstance(w, Real) or not math.isfinite(w) or w <= 0
           for w in weights.values()):
        raise ValueError('Weights must be finite and positive')
    audit_fixations(model)
    clone = model.clone()
    entries = []
    seen = set()
    # Reuse the parameters mapper for units, indices and initial time slices.
    # Its validation expects free variables, so temporarily clear clone fixity.
    fixed = [v for v in clone.component_data_objects(Var) if v.fixed]
    fixed_ids = {id(v) for v in fixed}
    for v in fixed:
        v.unfix()
    try:
        for record_tag in selected:
            record = resources.get(record_tag)
            single = ParameterCatalog(replacements=({record_tag: parameters.replacements[record_tag]}
                                                       if record_tag in parameters.replacements else {}), **{
                'initial_values' if record_tag in parameters.initial_values else 'parameters': [record_tag]})
            for variable, target in _prepare(clone, single, resources):
                if id(variable) in seen:
                    raise ValueError('Multiple records specify the same variable entry')
                seen.add(id(variable))
                if (id(variable) not in fixed_ids or variable.value is None
                        or not math.isclose(variable.value, target, rel_tol=1e-12, abs_tol=1e-12)):
                    raise ValueError(f'{record_tag}: parameters must already be applied at its recorded value')
                entries.append(dict(record_tag=record_tag, variable_path=record.variable_path,
                                    replaces=parameters.replacements.get(record_tag), index=variable.index(), variable=variable, target=target,
                                    unit=str(units.get_units(variable)), scale=_factor(variable),
                                    weight=weights.get(record_tag, 1)))
    finally:
        for v in fixed:
            v.fix()
    for objective in clone.component_data_objects(Objective, active=True):
        objective.deactivate()
    clone.add_component('parameters_relaxation', Block())
    block = clone.parameters_relaxation
    block.slack = Var(range(len(entries)), initialize=0)
    block.balance = Constraint(range(len(entries)))
    for i, entry in enumerate(entries):
        variable = entry['variable']
        variable.unfix()
        unit = units.get_units(variable)
        magnitude = variable / unit if unit is not None else variable
        block.balance[i] = block.slack[i] == entry['scale'] * (magnitude - entry['target'])
        set_scaling_factor(block.slack[i], 1)
        set_scaling_factor(block.balance[i], 1)
    # These slots are now soft observations on the diagnostic clone.
    softened = {entry['variable_path'] for entry in entries}
    clone._model_language_parameter_slots = {
        slot: entry for slot, entry in clone._model_language_parameter_slots.items()
        if entry['variable_path'] not in softened}
    clone._model_language_initial_fixations = {
        pair for pair in clone._model_language_initial_fixations
        if pair[0] not in {e['variable_path'] for e in entries}}
    block.objective = Objective(expr=sum(e['weight'] * block.slack[i]**2 for i, e in enumerate(entries)))
    return ParameterRelaxation(clone, entries)
