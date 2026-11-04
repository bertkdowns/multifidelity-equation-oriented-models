"""Bottom-up local solves with reversible, DM-guided boundary closures."""

from dataclasses import dataclass, field
import math

from .initialization import apply_starting_values, initialize_custom_models
from .selection import _partition
from .scaling import apply_scaling, export_scaling, rank_inputs


@dataclass
class InitializationStage:
    model_path: str
    status: str = 'pending'
    initial_deficiency: int = 0
    remaining_deficiency: int = 0
    temporary_fixes: list[dict] = field(default_factory=list)
    unresolved_variables: list[str] = field(default_factory=list)
    overconstrained_constraints: list[str] = field(default_factory=list)
    missing_starting_values: list[str] = field(default_factory=list)
    invalid_starting_values: list[str] = field(default_factory=list)
    invalid_result_values: list[str] = field(default_factory=list)
    callbacks: list[str] = field(default_factory=list)
    solver_termination: str | None = None
    max_constraint_violation: float | None = None
    max_scaled_constraint_violation: float | None = None
    numerical_selections: list[dict] = field(default_factory=list)
    fallback_variable_scales: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class InitializationResult:
    success: bool = False
    stages: list[InitializationStage] = field(default_factory=list)
    starting_value_record_ids: list[str] = field(default_factory=list)
    failed_model: str | None = None
    scaling_callbacks: list[str] = field(default_factory=list)
    fallback_variable_scales: list[str] = field(default_factory=list)


def _valid_guess(variable):
    guess = variable.value
    return guess is not None and math.isfinite(guess) and (
        variable.lb is None or guess >= variable.lb
    ) and (variable.ub is None or guess <= variable.ub)


def _constraint_violation(block, *, scaled=False):
    """Absolute residuals in each constraint's own units (not a scaled norm)."""
    from pyomo.environ import Constraint, value
    from pyomo.core.expr.visitor import identify_variables

    maximum = 0.0
    for constraint in block.component_data_objects(Constraint, active=True):
        if any(v.value is None for v in identify_variables(constraint.body)):
            return None
        try:
            body = value(constraint.body)
            lower = value(constraint.lower) if constraint.has_lb() else -math.inf
            upper = value(constraint.upper) if constraint.has_ub() else math.inf
            if not math.isfinite(body):
                return None
            from idaes.core.util.scaling import get_scaling_factor
            factor = get_scaling_factor(constraint, default=1) if scaled else 1
            maximum = max(maximum, factor * (lower - body), factor * (body - upper))
        except (ArithmeticError, ValueError):
            return None
    return maximum


def initialize_model(model, *, solver=None, information=None, specification=None,
                     excluded_record_ids=(), residual_tolerance=1e-6,
                     rank_tolerance=1e-10, tee=False):
    """Initialise a steady selected hierarchy, stopping at the first failed stage.

    Apply operating specifications before calling. Optional unused information
    supplies guesses, never new specifications. Only inputs on the current
    occurrence's boundary can be temporarily fixed. Their finite, in-bounds
    values are trialled one entry at a time, ranked by scaled null-space
    participation (trust then path/index break numerical ties). Recompute DM
    and the Jacobian after every accepted fix. The root is never closed
    artificially: it must be determined under the original specification.

    Missing free-variable guesses are reported; derived unknowns may be found by
    the solver. Missing/invalid boundary guesses cannot be used for closure.
    Callback/solver failures restore that stage's starting values. On success,
    values remain but all temporary fixes are released before the parent stage.
    Existing fixed values and constraint activation are preserved on either path.
    No fidelity switching, recycle tearing, or numerical recovery is performed.
    """
    from idaes.core.solvers import get_solver
    from pyomo.environ import Constraint, Var
    from pyomo.opt import check_optimal_termination

    order = getattr(model, '_model_language_initialization_order', None)
    if not order:
        raise ValueError('Model must be constructed by model_language.build_model')
    if model.fs.config.dynamic:
        raise ValueError('Bottom-up initialisation currently supports steady models only')
    if not math.isfinite(residual_tolerance) or residual_tolerance < 0:
        raise ValueError('residual_tolerance must be finite and nonnegative')
    if not math.isfinite(rank_tolerance) or not 0 < rank_tolerance < 1:
        raise ValueError('rank_tolerance must be finite and between 0 and 1')
    result = InitializationResult()
    trust = {}
    if information is not None:
        result.starting_value_record_ids = apply_starting_values(
            model, information, specification, excluded_record_ids=excluded_record_ids)
        trust = {information.get(i).variable_path: information.get(i).trust_rank
                 for i in result.starting_value_record_ids}
    elif specification is not None:
        raise ValueError('specification requires information for starting-value selection')
    solver = solver if solver is not None else get_solver(
        'ipopt', options={'max_iter': 500, 'tol': 1e-8})
    try:
        scaling = apply_scaling(model)
        result.scaling_callbacks = scaling.callbacks
        result.fallback_variable_scales = scaling.fallback_variables
    except Exception as error:
        result.failed_model = order[-1][0]
        result.stages.append(InitializationStage(
            model_path=result.failed_model, status='scaling_failed',
            error=f'{type(error).__name__}: {error}'))
        return result

    for position, (path, block, inputs) in enumerate(order):
        stage = InitializationStage(model_path=path)
        result.stages.append(stage)
        original = [(v, v.value, v.fixed) for v in block.component_data_objects(Var)]
        active_variables = list(block.component_data_objects(Var, active=True))
        stage.fallback_variable_scales = [v.name for v in active_variables
                                         if v.name in result.fallback_variable_scales]
        activation = [(c, c.active) for c in block.component_data_objects(Constraint, active=None)]
        success = False
        try:
            vp, cp = _partition(block)
            stage.initial_deficiency = len(vp.unmatched)
            stage.remaining_deficiency = len(vp.unmatched)
            is_root = position == len(order) - 1
            candidates = [
                (name, index, variable)
                for name, family in inputs.items()
                for index, variable in family.items()
            ]
            candidates.sort(key=lambda item: (-trust.get(item[0], 0), item[0], str(item[1])))
            while vp.unmatched and not cp.unmatched and not cp.overconstrained and not is_root:
                deficient = {id(v) for v in vp.unmatched + vp.underconstrained}
                eligible = [item for item in candidates if not item[2].fixed
                            and id(item[2]) in deficient and _valid_guess(item[2])]
                if not eligible:
                    break
                try:
                    ranked, diagnostic = rank_inputs(
                        block, eligible, len(vp.unmatched), rank_tolerance=rank_tolerance)
                except Exception as error:
                    stage.status = 'jacobian_failed'
                    stage.error = f'{type(error).__name__}: {error}'
                    break
                stage.numerical_selections.append(diagnostic)
                if diagnostic['numerical_rank'] < diagnostic['expected_rank']:
                    stage.status = 'numerical_rank_deficient'
                    stage.error = 'Jacobian rank is below the DM structural rank at the current guesses'
                    break
                accepted = False
                for name, index, variable in ranked:
                    variable.fix()
                    keep = False
                    try:
                        trial_vp, trial_cp = _partition(block)
                        keep = (len(trial_vp.unmatched) < len(vp.unmatched)
                                and not trial_cp.unmatched and not trial_cp.overconstrained)
                    finally:
                        if not keep:
                            variable.unfix()
                    if keep:
                        stage.temporary_fixes.append({
                            'variable_path': name, 'index': index, 'value': variable.value,
                            'unit': str(variable.get_units()), 'trust_rank': trust.get(name),
                            'deficiency_before': len(vp.unmatched),
                            'deficiency_after': len(trial_vp.unmatched),
                            'null_space_score': next(c['score'] for c in diagnostic['candidates']
                                                     if c['variable_path'] == name and c['index'] == index),
                        })
                        vp, cp = trial_vp, trial_cp
                        accepted = True
                        break
                if not accepted:
                    break
            stage.remaining_deficiency = len(vp.unmatched)
            stage.unresolved_variables = [v.name for v in vp.unmatched + vp.underconstrained]
            stage.overconstrained_constraints = [c.name for c in cp.unmatched + cp.overconstrained]
            stage.missing_starting_values = [v.name for v in active_variables if v.value is None]
            stage.invalid_starting_values = [v.name for v in active_variables
                                            if (v.value is not None or v.fixed) and not _valid_guess(v)]
            if stage.status != 'pending':
                pass
            elif stage.overconstrained_constraints:
                stage.status = 'overconstrained'
            elif stage.remaining_deficiency:
                stage.status = 'underconstrained'
                stage.error = ('Root requires additional operating specifications' if is_root else
                               'No eligible boundary input guess closes the remaining freedom')
            elif stage.invalid_starting_values:
                stage.status = 'invalid_starting_values'
            else:
                # JSON parents must not rerun callbacks belonging to children
                # that have already been initialised in earlier stages.
                if not hasattr(block.relationship, 'models'):
                    stage.callbacks = initialize_custom_models(block.relationship)
                # Re-evaluate row scales at the closed local problem. Public
                # variable identities, equations and physical units stay intact.
                _, diagnostic = rank_inputs(block, [], 0, rank_tolerance=rank_tolerance)
                stage.numerical_selections.append(diagnostic)
                if diagnostic['numerical_rank'] < diagnostic['expected_rank']:
                    stage.status = 'numerical_rank_deficient'
                    stage.error = 'Closed local Jacobian is numerically rank deficient'
                    raise ValueError(stage.error)
                residual = _constraint_violation(block, scaled=True)
                # A leaf hook may already satisfy the local equations. Otherwise
                # use the normal solver to complete the local initialisation.
                if residual is None or residual > residual_tolerance or (is_root and vp.square):
                    export_scaling(block)
                    options = ({'nlp_scaling_method': 'user-scaling'}
                               if getattr(solver, 'name', 'ipopt').startswith('ipopt') else {})
                    solved = solver.solve(block, tee=tee, options=options)
                    stage.solver_termination = str(solved.solver.termination_condition)
                    residual = _constraint_violation(block, scaled=True)
                    if not check_optimal_termination(solved):
                        stage.status = 'solver_failed'
                stage.max_constraint_violation = _constraint_violation(block)
                stage.max_scaled_constraint_violation = residual
                if stage.status == 'pending':
                    invalid = [v.name for v in active_variables if not _valid_guess(v)]
                    if residual is None or residual > residual_tolerance or invalid:
                        stage.status = 'residual_failed'
                        stage.invalid_result_values = invalid
                        stage.error = 'Local result fails residual or variable-value checks'
                    else:
                        stage.status = 'initialized'
                        success = True
        except Exception as error:
            if stage.status == 'pending':
                stage.status = 'error'
            stage.error = stage.error or f'{type(error).__name__}: {error}'
        finally:
            for variable, guess, fixed in original:
                if fixed or not success:
                    variable.set_value(guess, skip_validation=True)
                variable.fixed = fixed
            for constraint, enabled in activation:
                constraint.activate() if enabled else constraint.deactivate()
        if not success:
            result.failed_model = path
            return result
    result.success = True
    return result
