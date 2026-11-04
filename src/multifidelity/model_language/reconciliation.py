"""Clone-based, weighted least-squares relaxation of selected specifications."""

from dataclasses import dataclass
import math
from numbers import Real

from .specification import SpecificationDocument, _prepare
from .scaling import _factor


@dataclass
class SpecificationRelaxation:
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


def relax_specifications(model, specification, information, *, weights=None):
    """Return an independent diagnostic clone with information fixes softened.

    Minimize sum(weight * (scale * (value - target))**2). Scales multiply native
    variable magnitudes, defaulting to 1. Weights are positive finite numbers keyed
    by record id. All original equations and bounds remain hard; other fixed
    variables remain fixed. Existing objectives are deactivated on the clone.
    Selected specifications must already be applied at their recorded values.
    Neither source values/fixity nor information records are changed. A nonzero
    optimum identifies joint reconciliation changes, not a unique faulty sensor.
    """
    from pyomo.environ import Block, Constraint, Objective, Var, units
    from idaes.core.util.scaling import set_scaling_factor
    if not isinstance(specification, SpecificationDocument):
        specification = SpecificationDocument.model_validate(specification)
    weights = dict(weights or {})
    selected = specification.specifications + specification.initial_values
    if not selected:
        raise ValueError('Select at least one specification to relax')
    if set(weights) - set(selected):
        raise ValueError('Weights must refer to selected information record ids')
    if any(isinstance(w, bool) or not isinstance(w, Real) or not math.isfinite(w) or w <= 0
           for w in weights.values()):
        raise ValueError('Weights must be finite and positive')
    clone = model.clone()
    entries = []
    seen = set()
    # Reuse the specification mapper for units, indices and initial time slices.
    # Its validation expects free variables, so temporarily clear clone fixity.
    fixed = [v for v in clone.component_data_objects(Var) if v.fixed]
    fixed_ids = {id(v) for v in fixed}
    for v in fixed:
        v.unfix()
    try:
        for record_id in selected:
            record = information.get(record_id)
            single = SpecificationDocument(**{
                'initial_values' if record_id in specification.initial_values else 'specifications': [record_id]})
            for variable, target in _prepare(clone, single, information):
                if id(variable) in seen:
                    raise ValueError('Multiple records specify the same variable entry')
                seen.add(id(variable))
                if (id(variable) not in fixed_ids or variable.value is None
                        or not math.isclose(variable.value, target, rel_tol=1e-12, abs_tol=1e-12)):
                    raise ValueError(f'{record_id}: specification must already be applied at its recorded value')
                entries.append(dict(record_id=record_id, variable_path=record.variable_path,
                                    index=variable.index(), variable=variable, target=target,
                                    unit=str(units.get_units(variable)), scale=_factor(variable),
                                    weight=weights.get(record_id, 1)))
    finally:
        for v in fixed:
            v.fix()
    for objective in clone.component_data_objects(Objective, active=True):
        objective.deactivate()
    clone.add_component('specification_relaxation', Block())
    block = clone.specification_relaxation
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
    block.objective = Objective(expr=sum(e['weight'] * block.slack[i]**2 for i, e in enumerate(entries)))
    return SpecificationRelaxation(clone, entries)
