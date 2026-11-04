"""Multiplicative variable scales, native hooks, and local Jacobian row scaling."""

from copy import deepcopy
from dataclasses import dataclass, field
import math


@dataclass
class ScalingReport:
    callbacks: list[str] = field(default_factory=list)
    fallback_variables: list[str] = field(default_factory=list)


def _factor(variable):
    from idaes.core.util.scaling import get_scaling_factor
    factor = get_scaling_factor(variable, default=1)
    if not math.isfinite(factor) or factor <= 0:
        raise ValueError(f'{variable.name}: scale must be finite and positive')
    return factor


def apply_scaling(model):
    """Apply declarations and optional native scalers; missing factors default to 1.

    Explicit public declarations take priority at native bindings. Otherwise a
    native factor supplies the public factor, or public fallback 1 is converted
    to native units. Callbacks receive (native_block, config) and may only assign
    scaling suffixes. No values, fixity, or equations are changed.
    """
    from idaes.core.util.scaling import get_scaling_factor, set_scaling_factor
    from pyomo.environ import Block, Var, units

    report = ScalingReport()
    public_fallback = set()
    for family in model.component_objects(Var, descend_into=True):
        if not hasattr(family, '_model_language_scale'):
            continue
        declared = family._model_language_scale
        for variable in family.values():
            if declared is not None:
                set_scaling_factor(variable, declared)
            elif get_scaling_factor(variable) is None:
                set_scaling_factor(variable, 1)
                public_fallback.add(id(variable))
    for active in [model, *model.component_data_objects(Block, descend_into=True)]:
        metadata = getattr(active, '_model_language_scaling', None)
        if metadata is None:
            continue
        callback, config, public, native = metadata
        if callback is not None:
            callback(active.provider, deepcopy(config))
            report.callbacks.append(active.name)
        for name, variable in public.items():
            internal = native[name]
            conversion = units.convert_value(1, from_units=units.get_units(internal),
                                              to_units=units.get_units(variable))
            conversion -= units.convert_value(0, from_units=units.get_units(internal),
                                               to_units=units.get_units(variable))
            if not math.isfinite(conversion) or conversion <= 0:
                raise ValueError(f'{name}: invalid unit-conversion slope for scaling')
            if variable.parent_component()._model_language_scale is not None:
                set_scaling_factor(internal, _factor(variable) * conversion)
            elif get_scaling_factor(internal) is not None:
                set_scaling_factor(variable, _factor(internal) / conversion)
                public_fallback.discard(id(variable))
            else:
                set_scaling_factor(internal, _factor(variable) * conversion)
                if id(variable) in public_fallback:
                    report.fallback_variables.append(internal.name)
    for variable in model.component_data_objects(Var, active=True):
        if get_scaling_factor(variable) is None:
            set_scaling_factor(variable, 1)
            report.fallback_variables.append(variable.name)
        elif id(variable) in public_fallback:
            report.fallback_variables.append(variable.name)
        _factor(variable)
    report.fallback_variables = sorted(set(report.fallback_variables))
    return report


def _branch_expression(expression):
    """Differentiate Expr_if on its current branch, without changing the model."""
    from pyomo.core.expr.numeric_expr import Expr_ifExpression
    from pyomo.core.expr.visitor import identify_components, replace_expressions
    from pyomo.environ import value

    while branches := list(identify_components(expression, {Expr_ifExpression})):
        replacements = {id(node): node.arg(1 if value(node.arg(0)) else 2)
                        for node in branches}
        expression = replace_expressions(expression, replacements)
    return expression


def scaled_jacobian(block):
    """Evaluate derivatives and normalise rows after applying variable scales.

    The returned matrix includes active equalities and every active free variable,
    including isolated variables. All active constraints receive reciprocal
    infinity-row-norm factors. Zero rows use factor 1. Symbolic reverse AD allows
    linear derived variables to remain unset; required nonlinear guesses must
    exist. External-function derivatives use their native evaluate_fgh API.
    """
    import numpy as np
    from idaes.core.util.scaling import set_scaling_factor
    from pyomo.environ import Constraint, Var, value
    from pyomo.core.expr.visitor import identify_variables
    from pyomo.core.expr.calculus.derivatives import differentiate

    variables = [v for v in block.component_data_objects(Var, active=True) if not v.fixed]
    columns = {id(v): i for i, v in enumerate(variables)}
    constraints = list(block.component_data_objects(Constraint, active=True))
    matrix = np.zeros((len(constraints), len(variables)))
    variable_scales = np.array([_factor(v) for v in variables])
    for row, constraint in enumerate(constraints):
        expression = _branch_expression(constraint.body)
        local = [v for v in identify_variables(expression, include_fixed=False) if id(v) in columns]
        try:
            derivatives = differentiate(expression, wrt_list=local, mode='reverse_symbolic')
            for variable, derivative in zip(local, derivatives, strict=True):
                matrix[row, columns[id(variable)]] = value(derivative)
        except Exception as error:
            raise ValueError(f'{constraint.name}: cannot evaluate Jacobian: {error}') from error
    matrix /= variable_scales
    if not np.isfinite(matrix).all():
        raise ValueError('Jacobian contains nonfinite entries at the current guesses')
    for row, constraint in enumerate(constraints):
        norm = np.max(np.abs(matrix[row])) if len(variables) else 0
        factor = 1 / norm if norm else 1
        if not math.isfinite(factor):
            raise ValueError(f'{constraint.name}: nonfinite equation scaling factor')
        set_scaling_factor(constraint, factor)
        matrix[row] *= factor
    equality_rows = [i for i, c in enumerate(constraints) if c.equality]
    return matrix[equality_rows], variables, [constraints[i] for i in equality_rows]


def rank_inputs(block, candidates, structural_deficiency, *, rank_tolerance=1e-10):
    """Rank DM-eligible inputs by squared participation in the local null space."""
    import numpy as np
    from scipy.linalg import svd

    matrix, variables, constraints = scaled_jacobian(block)
    if len(variables):
        _, singular, vh = svd(matrix, full_matrices=True)
    else:
        singular, vh = np.array([]), np.empty((0, 0))
    threshold = rank_tolerance * singular[0] if len(singular) else 0
    rank = int(np.count_nonzero(singular > threshold))
    null_basis = vh[rank:].T
    scores = np.sum(null_basis**2, axis=1)
    by_id = {id(v): float(scores[i]) for i, v in enumerate(variables)}
    ranked = sorted(candidates, key=lambda item: -round(by_id[id(item[2])], 12))
    diagnostic = {
        'rows': len(constraints), 'columns': len(variables),
        'numerical_rank': rank, 'expected_rank': len(variables) - structural_deficiency,
        'nullity': len(variables) - rank, 'relative_rank_tolerance': rank_tolerance,
        'absolute_rank_threshold': float(threshold),
        'largest_singular_value': float(singular[0]) if len(singular) else 0,
        'smallest_singular_value': float(singular[-1]) if len(singular) else 0,
        'zero_rows': [c.name for c, row in zip(constraints, matrix, strict=True) if not np.any(row)],
        'candidates': [{'variable_path': name, 'index': index, 'score': by_id[id(v)]}
                       for name, index, v in ranked],
    }
    return ranked, diagnostic


def export_scaling(block):
    """Expose local factors on the solve boundary for the IPOPT suffix interface."""
    from pyomo.environ import Var, Constraint, Suffix
    if not hasattr(block, 'scaling_factor'):
        block.scaling_factor = Suffix(direction=Suffix.EXPORT)
    for ctype in (Var, Constraint):
        for component in block.component_data_objects(ctype, active=True):
            block.scaling_factor[component] = _factor(component)
