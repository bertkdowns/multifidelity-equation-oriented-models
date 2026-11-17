"""Trust-ranked structural parameters for a fixed numerical model_document."""

from dataclasses import dataclass

from .resources import ResourceDocument
from .parameters import ParameterDocument, _prepare
from .replacement import pair_parameters, audit_fixations
from .variables import get_variable


@dataclass
class ParameterSelection:
    """Parameter choices and separate structural diagnostics (not a solve)."""

    parameters: ParameterDocument
    complete: bool
    initial_deficiency: int
    remaining_deficiency: int
    unresolved_variables: list[str]
    overconstrained_constraints: list[str]
    decisions: list[dict]
    pairing_error: str | None = None


def _partition(model):
    from pyomo.contrib.incidence_analysis import IncidenceGraphInterface
    from pyomo.environ import Constraint, Var

    # Supplying every free variable explicitly retains isolated variables.
    variables = list(model.component_data_objects(Var, active=True))
    variables = [v for v in variables if not v.fixed]
    constraints = [c for c in model.component_data_objects(Constraint, active=True)
                   if c.equality]
    return IncidenceGraphInterface(include_fixed=False).dulmage_mendelsohn(
        variables=variables, constraints=constraints,
    )


def select_parameters(model, resources: ResourceDocument, *,
                         prediction_targets=(), excluded_record_tags=(),
                         achieved_setpoint_tags=()) -> ParameterSelection:
    """Choose independent whole-family fixations using trust-ranked DM trials.

    The original model is unchanged. Existing fixations are mandatory context.
    Finalize the grid before calling. Target paths and excluded record tags are
    reserved; control setpoints require explicit achieved-setpoint authorization.
    Other physical/operating applicability must be filtered by the caller.
    Initial conditions, inequalities, numerical rank and solving are outside
    this structural policy. Apply the returned document separately.
    """
    if not isinstance(resources, ResourceDocument):
        raise TypeError("resources must be an ResourceDocument")
    if not hasattr(model, "_model_language_variables"):
        raise ValueError("Model must be constructed by model_language.build_model")
    audit_fixations(model)
    work = model.clone()
    targets = set(prediction_targets)
    for path in targets:
        get_variable(work, path)  # Catch misspelled prediction targets.
    excluded = set(excluded_record_tags)
    achieved = set(achieved_setpoint_tags)
    vp, cp = _partition(work)
    initial = len(vp.unmatched)
    selected = []
    decisions = []
    records = sorted(resources.records, key=lambda r: (-r.trust_rank, r.tag))
    for record in records:
        reason = None
        before = len(vp.unmatched)
        if cp.unmatched or cp.overconstrained:
            reason = "overconstrained system"
        elif record.tag in excluded:
            reason = "excluded record"
        elif record.variable_path in targets:
            reason = "reserved prediction target"
        elif (record.resource_type == "control_setpoint"
              and record.tag not in achieved):
            reason = "setpoint not explicitly assumed achieved"
        elif record.variable_path in {resources.get(i).variable_path for i in selected}:
            reason = "lower-ranked alternative"
        else:
            document = ParameterDocument(parameters=[record.tag])
            try:
                prepared = _prepare(work, document, resources)
            except (ValueError, TypeError) as error:
                reason = str(error)
            else:
                deficient = {id(v) for v in vp.unmatched + vp.underconstrained}
                if not any(id(v) in deficient for v, _ in prepared):
                    reason = "already structurally determined"
                else:
                    previous = [(v, v.value, v.fixed) for v, _ in prepared]
                    try:
                        for variable, target in prepared:
                            variable.fix(target)
                        trial_vp, trial_cp = _partition(work)
                    finally:
                        # Retain only accepted trials below.
                        for variable, value, fixed in previous:
                            variable.set_value(value, skip_validation=True)
                            variable.fixed = fixed
                    if (len(trial_vp.unmatched) < before
                            and not trial_cp.unmatched and not trial_cp.overconstrained):
                        for variable, target in prepared:
                            variable.fix(target)
                        selected.append(record.tag)
                        vp, cp = trial_vp, trial_cp
                    else:
                        reason = "trial does not reduce deficiency without overconstraint"
        decisions.append({
            "record_tag": record.tag, "variable_path": record.variable_path,
            "trust_rank": record.trust_rank, "value": record.value, "unit": record.unit,
            "resource_type": record.resource_type,
            "standard_deviation": record.standard_deviation,
            "selected": reason is None, "reason": reason,
            "deficiency_before": before, "deficiency_after": len(vp.unmatched),
        })
    parameters = ParameterDocument(parameters=selected)
    pairing_error = None
    try:
        parameters = pair_parameters(model, parameters, resources)
    except ValueError as error:
        pairing_error = str(error)
    for decision in decisions:
        if decision['selected']:
            decision['replaces'] = parameters.replacements.get(decision['record_tag'])
    return ParameterSelection(
        parameters=parameters,
        pairing_error=pairing_error,
        complete=not vp.unmatched and not cp.unmatched and not cp.overconstrained and pairing_error is None,
        initial_deficiency=initial, remaining_deficiency=len(vp.unmatched),
        unresolved_variables=[v.name for v in vp.unmatched + vp.underconstrained],
        overconstrained_constraints=[c.name for c in cp.unmatched + cp.overconstrained],
        decisions=decisions,
    )
