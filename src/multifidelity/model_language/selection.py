"""Trust-ranked structural specification for a fixed numerical implementation."""

from dataclasses import dataclass

from .information import InformationDocument
from .specification import SpecificationDocument, _prepare
from .replacement import pair_specification, audit_fixations
from .variables import get_variable


@dataclass
class SpecificationSelection:
    """Specification choices and separate structural diagnostics (not a solve)."""

    specification: SpecificationDocument
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


def select_specification(model, information: InformationDocument, *,
                         prediction_targets=(), excluded_record_ids=(),
                         achieved_setpoint_ids=()) -> SpecificationSelection:
    """Choose independent whole-family fixations using trust-ranked DM trials.

    The original model is unchanged. Existing fixations are mandatory context.
    Finalize the grid before calling. Target paths and excluded record IDs are
    reserved; control setpoints require explicit achieved-setpoint authorization.
    Other physical/operating applicability must be filtered by the caller.
    Initial conditions, inequalities, numerical rank and solving are outside
    this structural policy. Apply the returned document separately.
    """
    if not isinstance(information, InformationDocument):
        raise TypeError("information must be an InformationDocument")
    if not hasattr(model, "_model_language_variables"):
        raise ValueError("Model must be constructed by model_language.build_model")
    audit_fixations(model)
    work = model.clone()
    targets = set(prediction_targets)
    for path in targets:
        get_variable(work, path)  # Catch misspelled prediction targets.
    excluded = set(excluded_record_ids)
    achieved = set(achieved_setpoint_ids)
    vp, cp = _partition(work)
    initial = len(vp.unmatched)
    selected = []
    decisions = []
    records = sorted(information.records, key=lambda r: (-r.trust_rank, r.id))
    for record in records:
        reason = None
        before = len(vp.unmatched)
        if cp.unmatched or cp.overconstrained:
            reason = "overconstrained system"
        elif record.id in excluded:
            reason = "excluded record"
        elif record.variable_path in targets:
            reason = "reserved prediction target"
        elif (record.information_type == "control_setpoint"
              and record.id not in achieved):
            reason = "setpoint not explicitly assumed achieved"
        elif record.variable_path in {information.get(i).variable_path for i in selected}:
            reason = "lower-ranked alternative"
        else:
            document = SpecificationDocument(specifications=[record.id])
            try:
                prepared = _prepare(work, document, information)
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
                        selected.append(record.id)
                        vp, cp = trial_vp, trial_cp
                    else:
                        reason = "trial does not reduce deficiency without overconstraint"
        decisions.append({
            "record_id": record.id, "variable_path": record.variable_path,
            "trust_rank": record.trust_rank, "value": record.value, "unit": record.unit,
            "information_type": record.information_type,
            "standard_deviation": record.standard_deviation,
            "selected": reason is None, "reason": reason,
            "deficiency_before": before, "deficiency_after": len(vp.unmatched),
        })
    specification = SpecificationDocument(specifications=selected)
    pairing_error = None
    try:
        specification = pair_specification(model, specification, information)
    except ValueError as error:
        pairing_error = str(error)
    for decision in decisions:
        if decision['selected']:
            decision['replaces'] = specification.replacements.get(decision['record_id'])
    return SpecificationSelection(
        specification=specification,
        pairing_error=pairing_error,
        complete=not vp.unmatched and not cp.unmatched and not cp.overconstrained and pairing_error is None,
        initial_deficiency=initial, remaining_deficiency=len(vp.unmatched),
        unresolved_variables=[v.name for v in vp.unmatched + vp.underconstrained],
        overconstrained_constraints=[c.name for c in cp.unmatched + cp.overconstrained],
        decisions=decisions,
    )
