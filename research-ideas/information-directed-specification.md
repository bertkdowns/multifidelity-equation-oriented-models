# Information-directed specification and fidelity selection

These are proposed algorithms and experiment outlines, not implemented behavior
or established performance claims. They develop the measurement-based model
specification and information-gated refinement directions in
[the research questions](algorithms-and-hierarchies.md). The data conventions are
recorded in the [model-language README](../src/multifidelity/model_language/README.md#information-model).

Terminology follows the [model-language glossary](../src/multifidelity/model_language/terminology.md).
A specification plan is the content of a specification document, not another type.

## Two independently testable research problems

1. **Specification at a fixed implementation:** Given selected relationships,
   available information and quantities of interest, choose which variables to
   fix to obtain a structurally determined model, then assess numerical solution
   and prediction quality. Keep fidelity choices fixed within each comparison.
2. **Measurement-directed fidelity selection:** Given the same information and
   quantities of interest, choose an implementation. Start simple, expand one
   branch, inspect the changed information requirements, and repeat. Use a fixed
   specification policy to assess candidate implementations so that changes in
   selection behavior are not confounded with changes in instance construction.

A selected implementation determines which equations exist. A specification document
chooses how to use information to specify those equations. The two decisions
interact, but neither algorithm's effectiveness should be inferred from the
other's results. Initialization algorithms remain a separate, deferred study.

## Information trust policy

Add `trust_rank` to each information record: an integer from 1 to 10, with larger
values receiving higher priority. For example, 10 may represent highly trusted
actual plant data and 1 a very rough estimate. These are assigned judgments, not
a claim that all plant data is reliable or that information type automatically
sets trust. Rank differences have no numerical probability interpretation.

Trust rank and standard deviation are distinct. Standard deviation describes
uncertainty in the record's unit; trust rank controls specification priority.
Do not compare raw standard deviations across different physical quantities,
translate rank into inverse variance, or treat small stated uncertainty as proof
that a record is unbiased or applicable.

Multiple records for one variable are **alternatives**, not additional independent
fixations. Normally use the highest-ranked applicable record. Lower-ranked records
remain available as fallbacks if the preferred record cannot be used; do not
average them, add multiple equalities, or use all their values in this baseline.
Fallbacks for the same variable do not add structural information. A possible
future numerical recovery policy could try a different record, but that is not
part of the initial trust-only selection rule.

For reproducibility, break equal-rank ties deterministically by record ID initially;
study the effect of ties rather than implying the tie-break is optimal. Record
eligibility must account for the selected implementation and operating conditions.
A control setpoint represents an actual variable value only under an explicitly
recorded achieved-setpoint assumption.

## Initial algorithm: greedy trust-ranked DM specification

Inputs are a concrete selected implementation, its information records, and the
quantity-of-interest specification. No fidelity changes occur within this algorithm.

1. Build the selected equation system without fixing values. Identify any genuinely
   mandatory external specifications separately; account for them explicitly.
   Reserve prediction targets and held-out evaluation records: do not fix a target
   to the observation whose prediction is being evaluated.
2. Form the equality equation–variable incidence graph and compute the
   Dulmage–Mendelsohn (DM) decomposition. Include the unmatched variables as well
   as the underconstrained partition when finding specification candidates.
   Explicitly account for isolated variables rather than silently losing them
   because they do not appear in an equation. Report an overconstrained subsystem
   as a structural problem; adding fixed variables is not its remedy.
3. Find applicable information records targeting eligible free variables in those
   deficient regions. Consider each variable's best available record and rank
   candidates by descending `trust_rank`, with the documented tie-break.
4. Tentatively fix the highest-ranked eligible variable to its record value,
   converting units where required. Recompute matching/DM. Accept if the number
   of unmatched unknowns decreases without introducing an overconstrained region;
   otherwise undo the trial, record the reason and consider another candidate.
5. Repeat after each accepted choice. Variables leave the candidate set as other
   specifications make them determined. Do not fix every variable from the initial
   underconstrained set.
6. Stop when no structural deficiency remains, or no applicable candidate can
   reduce it. Return a complete or incomplete specification document. In the latter
   case, list unresolved regions and missing eligible information, rather than
   inventing values or fixing the prediction target.
7. For structurally complete plans, attempt a numerical solve using a common,
   established initialization procedure. Record convergence, feasibility and
   relevant outputs separately from structural status. The first algorithm need
   not include automatic numerical backtracking.

For `x + y = 10`, either `x` or `y` can be specified. After fixing the more trusted
measurement of `x`, `y` is determined and must not also be fixed. The DM partition
provides choices, not a unique required specification list.

This algorithm can specify a declared output while leaving a declared input free.
Input/output directions and `determines` remain the default forward-calculation
contract and useful metadata; numerical specification selection uses the actual
equations. It is an extension beyond the existing `required_inputs()` query, not
an assertion that default input coverage and structural analysis are equivalent.

Initially, use selected measured/estimated/assumed central values as **fixed
specifications**, an explicit approximation even when their standard deviations
are nonzero. A fallback estimate used here is a fixed assumption, not merely a
solver initial guess. Sufficient structurally independent, admissible fallbacks
may complete a plan; an arbitrary number of guesses cannot guarantee completeness,
feasibility, uniqueness or physical adequacy.

DM references: [Pyomo decomposition documentation](https://pyomo.readthedocs.io/en/6.9.3/api/pyomo.contrib.incidence_analysis.dulmage_mendelsohn.dulmage_mendelsohn.html)
and [IDAES structural-singularity example](https://idaes-examples.readthedocs.io/en/2.6.0/docs/diagnostics/structural_singularity_doc.html).

## Auditable specification document

The result should record:

- Model/implementation identity, quantities of interest, information records used,
  trust policy and deterministic tie-break.
- Each fixed variable path, chosen record ID, applied value/unit, trust rank,
  information type and retained standard deviation.
- Records skipped or rejected and reasons: lower-ranked alternative, target
  reserved for prediction/evaluation, unavailable path, already determined,
  incompatible or inapplicable data, or a structurally inadmissible trial.
- Assumptions used, including fixed fallback estimates and any achieved-setpoint
  assumption; distinguish these from independently known data.
- Structural deficiency before/after accepted choices, any unresolved regions,
  and an explicit complete/incomplete status.
- Numerical solve status separately, if solving was attempted. Do not label a
  structurally complete plan as guaranteed solvable or unique.

The intended successful result is that all required degrees of freedom are
resolved using available evidence and explicit fallbacks, with every choice
traceable. The algorithm must also be able to report that the evidence is insufficient.

## Experiment A: specification with fidelity held fixed

**Question:** Does trust-ranked structural specification choose useful independent
specifications and reduce reliance on weak assumptions while retaining numerical
solvability and predictive quality?

Start with a bounded steady-state heat-pump example and controlled information
records. Run comparisons separately for an aggregate implementation and a cycle
implementation; do not switch fidelity during a trial. Establish that the chosen
case has meaningful alternative specification sets.

Vary information availability/location, trust ordering, competing records for a
variable, and completeness/quality of fallback assumptions. Include cases where
there is insufficient information and where equal global equation/variable counts
hide local structural deficiencies. Separate initial guesses from fixed assumptions.

Compare the proposed algorithm with a manual specification, the default declared-
input specification where applicable, and random-order structurally admissible
selection. For small cases, enumerate admissible specification sets as an offline
benchmark; greedy trust ordering is not claimed to give the numerically best set.

Measure structural completion and rejection behavior, solve/feasibility success,
required assumptions and their ranks, held-out quantity-of-interest error,
sensitivity to record ordering/ties, and total planning plus solve cost. Keep
model equations, information, targets, solver/initialization procedure and trial
conditions identical across specification strategies. Use synthetic truth or
independent held-out observations, not the fixed target itself, for evaluation.

## Experiment B: measurement-directed fidelity selection

**Question:** With a fixed specification policy, can incremental refinement identify
representations supported by available information and improve predictions at an
acceptable information and computational cost?

Start with the simplest declared implementation, expand one branch at a time,
inspect additional/released information requirements, construct a specification
plan using the same policy for each candidate, and evaluate supported candidates.
Define the initial low-detail choices and expansion order explicitly; depth or
an arbitrary relationship ordering alone is not a reliable definition of simplicity.

Hold information availability and the engineering question constant within each
comparison. Compare aggregate-only, a detailed baseline where supportable, the
incremental policy, and exhaustive candidate evaluation for a small hierarchy.
An optional manually selected implementation provides another reference.

Measure which representations are supportable, held-out prediction error, dependence
on assumptions, selected equipment/property detail, planning/solve cost including
failures, and sensitivity to expansion order. Do not rank candidates solely by
training residual, convergence, representation depth or number of detailed units.
The present quantity-of-interest specification has no tolerances: report tradeoffs
rather than invent an accuracy threshold or claim an automatic reliability-based
stopping rule. Define a finite candidate budget for an initial experiment.

After independent tests, study the combined loop. If instance construction fails
or a prediction deteriorates, retain enough provenance to distinguish inadequate
evidence/specification, numerical difficulty and an unsuitable representation.

## Future studies beyond the initial fixed-value approximation

- **Noisy information:** conduct a literature review of robustness to noisy or
  biased measurements, Monte Carlo uncertainty propagation, weighted data
  reconciliation and related estimation methods. Discuss how uncertainty,
  correlations and bias change both specification choices and fidelity selection.
  Assess whether fixing uncertain values is an acceptable approximation for our
  experiments; do not implement a reconciliation objective in the initial method.
- **Jacobian-guided specification replacement:** a structurally complete system
  may be numerically singular or ill-conditioned. Investigate scaled Jacobian
  rank/conditioning or singular values at meaningful states, and whether releasing
  one selected specification and replacing it with another eligible record improves
  conditioning and solve reliability. Control for variable/equation scaling and
  record any loss of trust when replacing a stronger record with a weaker one.
  This is numerical recovery/selection research, not a guarantee obtainable from
  DM alone; it requires an evaluation point or candidate solution.
