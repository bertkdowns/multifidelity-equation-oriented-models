# Canonical variables and specification replacement

Research proposal, investigated 6 November 2026. This note connects
[pyomo-replace](https://github.com/bertkdowns/pyomo-replace) to the current
[information-directed specification study](information-directed-specification.md)
and [initialisation proposal](initialisation.md). The recommendations below are
proposed changes, not implemented features or demonstrated improvements.

## What replacement means

The useful idea is to give each selected implementation an explicit **default
specification basis**: variables normally fixed to close the model. A replacement
releases one of those default specifications and fixes another variable instead.
The physical equations remain unchanged. Replacement does not equate the two
variables, substitute one symbol for another, or replace an equipment model.
The two variables can have different physical dimensions: outlet enthalpy can
replace heater duty because the energy balance relates them.

The source inspected is pyomo-replace commit
[`026d9d51594fa6d72fcd8fce732dd7569eb98828`](https://github.com/bertkdowns/pyomo-replace/tree/026d9d51594fa6d72fcd8fce732dd7569eb98828).
Its [README](https://github.com/bertkdowns/pyomo-replace/blob/026d9d51594fa6d72fcd8fce732dd7569eb98828/readme.md)
introduces default canonical variables and paired replacement. The actual
[specification implementation](https://github.com/bertkdowns/pyomo-replace/blob/026d9d51594fa6d72fcd8fce732dd7569eb98828/specifications.py)
is more specific:

- A flowsheet owns one `SpecificationState`; canonical registration fixes the
  registered variables immediately. Each registration carries a category.
- `replace(canonical, replacement)` requires a fixed registered canonical and an
  unfixed noncanonical replacement belonging to that flowsheet. It unfixes the
  canonical and fixes the replacement at its existing value. It performs a
  flowsheet DM decomposition and reverses the exchange when constraints are
  unmatched. An immutable `Replacement` stores the pair and canonical category.
- Queries distinguish replacements internal to a block, replacements supplied
  outside the block, and replacements supplied by the block for another block.
  Temporary suspension restores canonical closure for a local solve and then
  restores replacement fixed values and statuses.
- Automatic inlet registration finds inlet ports with no sources. Equipment
  also explicitly registers operational/design quantities: the
  [heater wrapper](https://github.com/bertkdowns/pyomo-replace/blob/026d9d51594fa6d72fcd8fce732dd7569eb98828/unit_models/heater.py)
  registers heat duty, pressure change when enabled, and holdup-related variables
  when enabled. Canonicals are therefore broader than inlet thermodynamic states.

The [staged initialiser](https://github.com/bertkdowns/pyomo-replace/blob/026d9d51594fa6d72fcd8fce732dd7569eb98828/initialisation.py)
first solves with canonicals fixed at guesses, then restores only replacements
internal to that unit and solves again. Cross-unit specifications are deferred to
the larger coupled solve. The
[tests](https://github.com/bertkdowns/pyomo-replace/blob/026d9d51594fa6d72fcd8fce732dd7569eb98828/tests/test_single_operation.py)
exercise replacement identity, categories, canonical membership, guesses and
restoration of internal/external replacement states. They do not establish
convergence or mathematical validity for arbitrary replacement pairs. The README's
TODO to add tests is stale relative to the inspected source.

## Mapping the idea to this repository

The user's proposed seed is sensible: input families with no selected defining
relationship or incoming connection are the **candidate canonical variables**.
This is close to [`required_inputs()`](../src/multifidelity/model_language/requirements.py),
which traverses selected occurrences and returns input fields absent from their
supplied set. It already preserves paths and dimensions without constructing a
numerical model. But its documented contract is declaration coverage, not
solvability. Keep that distinction: initially call this a default specification
*proposal*, validate it against the built equation system, and report missing,
redundant or unused candidates explicitly.

A canonical is relative to the selected implementation and solve boundary. A
child's input can be canonical for its isolated initialisation while being
supplied by another unit in the full flowsheet. A different fidelity may add a
relationship, remove a dependency, or introduce a parameter and therefore change
the appropriate basis. Do not make canonical status an immutable property of a
physical quantity or confuse it with a dynamic state variable.

[`builder.py`](../src/multifidelity/model_language/builder.py) builds authored
equations and separate, unit-converted connection equalities; connections are not
variable aliases. Its `determines` dependency bookkeeping validates the forward
model-authoring contract. Keep those directions intact when a solve fixes an
output and calculates an input: inverse specification should not require rewriting
`determines`, reversing a connection, or declaring a second definition. Dependency
reachability can suggest a plausible exchange but does not establish independent
closure.

The current [`SpecificationDocument`](../src/multifidelity/model_language/specification.py)
records information-record IDs to fix, plus dynamic initial-value IDs. Application
validates values, units and bounds before fixing; it rejects already-fixed entries.
It has no paired release operation. Prefer producing a new final record-ID
document and applying it once to a clean rebuilt model, with exchange history
kept as separate audit data, rather than calling `apply_specification()` twice
on an already specified model. The current
[`select_specification()`](../src/multifidelity/model_language/selection.py) instead
starts from free variables and greedily accepts trust-ranked family fixes that
reduce structural deficiency. These are complementary workflows:

1. Use the existing selector to discover a closure when no trusted default basis
   is available, and as an independent experimental baseline.
2. Offer a canonical-first plan when a validated default closure exists. Attach
   evidence to retained canonical specifications, then consider exchanges that
   admit better information or satisfy the engineering question.
3. Represent the resulting fixed set as a portable specification document, with
   an explicit optional exchange trace explaining which default specification
   was released, which information record replaced it, and why it was accepted.

Do not silently fix canonicals on ordinary `build_model()`. That would change the
current free-model/explicit-specification contract and obstruct the selector's
trials. Generate and validate the default plan separately; derive its numerical
fixed state only when applying that plan. Missing information must remain missing:
registration alone is no justification for fixing an arbitrary default value.

## Necessary checks beyond one-for-one bookkeeping

Let the active equality system be `F(x) = 0`, with a canonical set `C`. After
fixing `C`, the remaining Jacobian columns must form a nonsingular square system
locally. Replacing `c` with `z` proposes `C' = (C - {c}) union {z}`. Equal counts
preserve a degree-of-freedom count; they do not prove that `C'` determines a
solution.

For example, `x + y = 1` and `2*x + 2*y = 2` have the same counts and incidence
pattern as two independent equations, but their Jacobian is rank deficient.
Conversely, a structurally legitimate exchange through `z = x*x` fails local
invertibility at `x = 0` and has branch ambiguity elsewhere. A real solve can also
fail because of bounds, phase restrictions or inconsistent information.

The inspected pyomo-replace `validate()` uses an IDAES degree-of-freedom count;
its replacement check rejects unmatched constraints but does not explicitly
reject unmatched variables, compare indexed-family cardinalities, or evaluate
numerical rank. Its external-replacement bookkeeping test even uses two isolated
variables without a linking equation. This is evidence for a useful state-management
pattern, not proof that its API guarantees valid closure for every input.

Here, every proposed complete plan or exchange should therefore:

1. Resolve stable public paths to concrete entries and validate the active
   implementation, domain/index coverage and information eligibility. A time
   trajectory and an initial-time slice are different specification scopes.
2. On a trial model, release and fix the whole intended sets atomically, including
   converted replacement values. Check the full resulting free-variable universe,
   including isolated variables, and reject both under- and overdetermination.
   Test coupled exchanges jointly; individually permissible pairs can conflict.
3. Assess the scaled equality Jacobian at a valid operating-point guess. Record
   rank and conditioning separately from structural acceptance and check
   numerical solve/feasibility separately again. A local rank check is not a
   global uniqueness guarantee. When a valid evaluation point is unavailable,
   report numerical validity as unchecked; structural planning must not invent
   operating values or claim numerical acceptance.
4. Preserve values, statuses and original evidence when rejecting or undoing a
   plan. Store a released canonical's value as a guess, not a still-active
   measurement constraint. Avoid assuming exchanged variables have compatible
   units; each record must match the variable it actually specifies.

[`hierarchical_initialization.py`](../src/multifidelity/model_language/hierarchical_initialization.py)
already recomputes DM and uses the scaled Jacobian/nullspace input ranking for
*temporary local boundary closures*, rejecting numerical rank deficiency. Reuse
that numerical analysis where appropriate; permanent specification exchange is a
new use of it, not the introduction of Jacobian analysis to the project. Keep
rank tolerance, scaling and operating point in the experiment record.

## A concrete heat-pump example

Suppose an exposed water state has canonical pressure `p` and specific enthalpy
`h`; a property relationship computes temperature `T`. With valid pressure
information and a more useful temperature measurement, replace the `h`
specification with the `T` record. Retain the property equation, keep pressure
specified, release enthalpy, and solve for it. If the relationship is written as
`T = T(p, h)`, local exchange requires nonzero sensitivity to `h` with pressure
held fixed. Near or within phase-change regions, temperature may be a poor or
nonunique substitute for enthalpy. Validate the selected property formulation and
operating domain instead of assuming every state coordinate exchange works.

At equipment level, specified compressor outlet pressure can replace a pressure
rise specification, or measured heat-pump power can replace an operational degree
of freedom if the coupled equations support that inverse problem. Reserve power
as a prediction target when evaluating power prediction; its measurement must
not become an exchange merely because it has high trust. Exchanging a setpoint
also requires the existing achieved-setpoint assumption.

## How current research approaches should change

**Specification research:** add a canonical-first exchange policy beside the
current free-start greedy policy. Compare them at the same fixed implementation,
with identical eligible information, target exclusions, initialisation and solver
settings. A path-based pair is an explanatory choice, not a unique physical
causal assignment; several canonical releases may admit the same measurement.
Use trust rank to prioritize information, with structural and numerical checks
for admissibility. A canonical-first greedy policy can retain weak default
records that prevent a better joint choice; do not assume local trust-improving
exchanges find the same or best closure as the from-free selector. Assess joint
independence before interpreting trust gains.
The existing proposal's future Jacobian replacement study becomes a concrete
basis-exchange experiment rather than an informal fix/unfix heuristic.

**Initialisation research:** separate the desired final specification plan from
local temporary canonical closure. Try canonical closure with retained guesses,
then internal exchanges, then coupled external exchanges. Use the current
hierarchical initialiser as the baseline and preserve its structural/numerical
checks. Record cases where the default basis is itself poor. Do not assume a
second solve helps or invent an initialization advantage from easier examples.

**Fidelity selection:** recompute or revalidate the default and final bases after
each selected relationship changes. Carry information by stable physical paths;
retain valid canonical guesses and exchange intent only when the new formulation
supports them. Report invalidated exchanges and missing information. A change of
fidelity and a change of specification are separate decisions and must remain
separately attributable in experiments.

**Recycle and definition handling:** replacement cannot remove a redundant
continuity equation or repair a structurally deficient physical formulation.
The current [mass-recycle definition test](../tests/test_mass_recycle_definition.py)
explicitly routes flow through a separate definition and leaves standard inlet
flow unused. First decide which independent equations and variables the physical
representation needs; then discover/validate a basis including unused variables.
Do not reinterpret that workaround as ordinary canonical exchange or hide an
unused variable by excluding it from the incidence graph.

**Dynamics:** defer general automatic exchange across trajectories, initial
conditions and derivative specifications until a dedicated DAE experiment.
[`required_initial_values()`](../src/multifidelity/model_language/requirements.py)
is an authoring convention, not an independence proof. Start the proposed
exchange experiment in steady state, consistent with the current hierarchical
initialiser's scope.

## Smallest useful experiment and implementation sequence

First implement a pure default-basis report over a selected implementation, with
its structural validation against the built model and clear unused-input
reporting. Next add an explicit paired exchange proposal on a clone and a
portable trace; preserve existing specification documents and evidence separation.
Only then compare automatic exchange selection with the current greedy selector.
Keep the initial prototype small rather than importing pyomo-replace's
flowsheet-mutation and IDAES-wrapper architecture wholesale.

Use an algebraic heater example to verify retained equations and paired fix/free
states, an invalid disconnected exchange, a structurally square but numerically
singular example, and indexed-family mismatch. Then use a heat-pump case with
fixed fidelity and alternative measured pressure/temperature/power records.
Report canonical coverage, accepted/rejected exchanges and reasons, structural
status, scaled rank/conditioning, solver convergence, prediction error on held-out
records, and elapsed effort. Compare final fixed sets as well as the exchange
trace: different exchange explanations can describe the same valid closure.

The research question is whether a validated, documented default basis makes
inverse specification more understandable and improves useful closure or
initialisation outcomes, while retaining the current measurement-driven
flexibility. This remains to be measured.
