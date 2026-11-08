# Canonical variables and specification replacement

Research proposal, investigated 6 November 2026 and revised 9 November 2026.
This note connects [pyomo-replace](https://github.com/bertkdowns/pyomo-replace)
to the current [specification study](information-directed-specification.md) and
[initialisation proposal](initialisation.md). The implementation below is proposed;
the existing specification API does not yet enforce it.

## Purpose and core rule

The main advantage is a physically understandable explanation of how a model is
specified: **we fix temperature instead of enthalpy at this point**, or **we fix
compressor outlet pressure instead of compressor work**. The model records which
normal input is now calculated, rather than leaving that choice implicit in a
list of fixed measurements. Numerical conditioning is a separate concern and is
not the motivation or a prerequisite for this implementation.

The core rule is:

> Whenever a variable is fixed, it must either be an input not defined by a
> constraint or connection in the selected model, or explicitly name such an
> input whose specification it replaces.

Call these undefined inputs **canonical inputs**. A replacement occupies one
canonical input's specification slot: the replacement variable is fixed and the
canonical input remains free to be calculated. It is not necessary to fix the
canonical input first, or even have a measurement for it. The pairing describes
what we choose to specify, not a required sequence of numerical mutations.

Physical equations remain unchanged. In particular, replacement does not alias
variables, substitute expressions, reverse connections or alter `determines`.
The replacement and canonical input can have different units. Temperature data
specifies temperature in its own unit; enthalpy becomes an unknown.

## Relation to pyomo-replace

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

## Discover canonical inputs for the selected model

Use [`required_inputs()`](../src/multifidelity/model_language/requirements.py)
as the starting point. It already walks selected occurrences and returns inputs
that are not supplied by their containing relationship's constraints, connections
or derivatives. Include equipment parameters and operational inputs, not just
stream state variables. Canonical status follows the selected implementation and
scope; it is not a permanent property of a variable declaration.

For a full flowsheet, a connected child input is not canonical merely because
its struct says `input`. If `compressor.inlet.enthalpy` is supplied by an upstream
connection, a temperature measurement at that inlet must name an unsupplied input
elsewhere in the selected model that it replaces. The explanation should show
both paths, even if they lie in different units. The connection stays active.

[`_validation.py`](../src/multifidelity/model_language/_validation.py) and the
selected traversal already provide the declaration-level determination metadata.
Reuse that metadata rather than infer canonical status from current Pyomo fixity.
Keep the existing direction and duplicate-definition checks. A dependency path
can help suggest a replacement, but the user or model author supplies the physical
choice initially; there is no need to introduce automatic pair discovery first.

An input that is unused still appears in this declaration-level list. Report it
as unused rather than presenting its replacement as a meaningful physical choice.
The rule makes specification choices explicit; it does not repair missing or
redundant physical equations, including recycle continuity problems.

## Store the replacement in the specification document

The replacement relationship must be required, portable specification data. It
cannot be merely an optional audit trace: otherwise a saved list of fixed
measurements loses the physical explanation and cannot enforce the rule on reload.
Keep values and units in the information document; the chosen replacement belongs
to the specification document because it depends on how we use that information.

A small extension to the current record-ID format is a `replacements` mapping
from selected information-record ID to canonical input path:

```json
{
  "specifications": ["inlet_pressure", "measured_temperature"],
  "replacements": {
    "measured_temperature": "state.enthalpy"
  },
  "initial_values": []
}
```

In this illustrative model, the `inlet_pressure` record targets canonical input
`state.pressure`; `measured_temperature` targets `properties.temperature`. The
result reads: **specify pressure directly; specify temperature instead of
enthalpy**. No enthalpy record or enthalpy default value is required.

Proposed semantics:

- A selected record with no replacement entry must target a canonical input.
- A record targeting any other variable must have an explicit replacement entry.
  This includes input fields already supplied by constraints or connections.
- Each replacement key must name a selected record; its value must name a
  canonical input in the selected implementation and scope.
- A canonical slot can be used once: either directly or by one replacement.
  Reject two replacements for it, or a direct fixation together with its replacement.
  Also reject duplicate fixed targets and self-replacement.
- A replacement always names the original canonical input. Do not create chains
  of replacements through other outputs. Changing temperature to another measured
  quantity updates the occupant of the same canonical slot.
- Initially exchange whole families with matching index domains and scope. Do not
  silently exchange a scalar for a trajectory or a full trajectory for an initial
  slice. More general group exchanges can be added when an example requires them.

An omitted `replacements` mapping defaults to empty. Existing documents selecting
only canonical inputs remain valid. Existing documents fixing outputs or supplied
inputs need explicit pair annotations; accepting them without annotations would
break the proposed rule. A migration report should list those records and request
an input choice, rather than silently guess a physical explanation.

This changes the earlier proposal: the final fixed set alone is insufficient.
An optional audit can still record selection decisions and rejected alternatives,
but the chosen replacement pairs are part of the specification itself.

## Apply and maintain the specification

Extend [`SpecificationDocument` and `apply_specification()`](../src/multifidelity/model_language/specification.py)
with the mapping above. A small shared helper should resolve the canonical slot
for each requested fixation and be used by both manual application and automatic
selection.

1. Resolve the selected implementation, canonical inputs, record paths and pairs.
   Build a slot table containing canonical input, fixed variable, record ID and
   whether this is direct specification or replacement.
2. Validate slot ownership and index scope, then perform the existing value,
   unit, bounds and record-eligibility checks before changing any variable.
3. Fix only the chosen targets. A canonical input occupied by a replacement must
   remain free; its current value may remain as a solver guess. Canonical inputs
   with no specification remain free and are reported as unspecified.
4. Retain the slot table on the numerical instance, using stable paths so it can
   be reconstructed after cloning or rebuilding. Explain each fixed target as
   either a direct input or an explicit replacement.

Ordinary `build_model()` should continue to build a free model. Discovering a
canonical input does not fix it, and a declared default remains a starting guess.
Partial specification documents remain useful; the invariant applies to each
fixation without requiring all slots to be occupied.

For a first implementation, apply the final document once to a clean model,
retaining the existing rejection of already-fixed targets. If interactive
replacement is needed later, replace the current occupant atomically: release
its fixation, fix the new target, and update the slot table together. Restore
values, fixity and slot ownership on failure. Releasing an occupant leaves its
canonical slot unspecified; it must not automatically fix a guessed canonical
value as a new operating specification.

Inspect pre-existing public fixations at entry: they need corresponding direct
input or replacement provenance. Unknown output fixations should be reported,
rather than treated as unexplained mandatory context. Public APIs and examples
should use the managed application path. Raw Pyomo `.fix()` remains technically
possible, so a fixation audit at initialization/solve entry should detect a bypass
and identify the missing input or replacement declaration.

## Explain the physical choices accurately

For a pressure/enthalpy state, the natural example is:

| Canonical input | Fixed quantity | Explanation |
| --- | --- | --- |
| `state.pressure` | `state.pressure` | Specify pressure directly. |
| `state.enthalpy` | `properties.temperature` | Specify temperature instead of enthalpy; calculate enthalpy using the property equations. |

For a compressor whose formulation takes work as an undefined input, fixing
outlet pressure can explicitly replace that work input. The pressure, efficiency
and energy equations then determine the work required.

The current [`compressor.json`](../src/multifidelity/model_language/models/compressor.json)
has a different forward contract: `parameters.pressure_rise` is an input and
`performance.work` is an output. With this definition, the corresponding pair is
**outlet pressure instead of pressure rise**. Specifying work would itself replace
an input, such as pressure rise. To support the exact explanation **outlet
pressure instead of work**, provide a work-input formulation with the appropriate
`determines` declarations; do not label the current work output a canonical input.
The physical equations can often stay the same while the authored forward
contract differs.

These examples show why the pair is model-specific information. A list containing
only a temperature or pressure record cannot express which input is to be
calculated, especially when several inputs could be released.

## Update automatic specification selection

The current [`select_specification()`](../src/multifidelity/model_language/selection.py)
can choose any structurally admissible fixed variable without recording what it
replaces. Update the proposed main workflow so it returns both chosen record IDs
and their replacement mappings. Every selected fixation must satisfy the core
rule, including those chosen automatically.

Start with manually supplied or model-authored candidate pairs. Direct canonical
records need no annotation. For other records, consider only explicitly nominated
canonical slots. Trust rank can order records, and the existing DM trials can
still check structural admissibility, but they cannot supply a physical explanation
by themselves. When several slots are possible, expose the choice rather than
use an arbitrary unmatched variable as its explanation.

The existing unrestricted selector can remain an experimental comparison. Its
output must acquire explicit pairs before it is applied through the proposed
specification API. High trust does not waive pairing, achieved-setpoint assumptions
or prediction-target exclusions. A power measurement reserved for evaluation
must not be used to specify power via a replacement.

The main result should be a readable slot report: **what is fixed, what input it
replaces, where both quantities belong, and which information record supplies
the value**. An unoccupied slot reports missing specification; a replacement
reports a deliberate inverse calculation. These are more useful explanations
than presenting only unmatched-variable names.

## Initialisation, providers and fidelity changes

The same rule should govern temporary initialisation fixes, with a separate
lifetime and solve scope. The existing
[`hierarchical_initialization.py`](../src/multifidelity/model_language/hierarchical_initialization.py)
already restricts temporary closures to exposed input candidates. Within an
isolated child solve, a boundary input can be canonical because the parent's
connection equation is outside that solve. Record that local scope and release
the temporary fixation before the parent solve. Any future temporary fixation of
an output must name the local canonical input it replaces.

Operating specifications and temporary closures must use coordinated slot
ownership. In particular, a permanently specified temperature replacing enthalpy
must prevent an initializer from also fixing that enthalpy in the same active
problem. Existing DM and numerical checks may remain, but slot provenance is
what explains the intended calculation. Restoring canonical closure for a staged
solve must be an explicit temporary suspension of the replacement, followed by
restoration of the final specification.

Custom providers must preserve this explanation when transferring public fixes
to native variables. A native counterpart inherits the same specification and
scope; it does not consume a second canonical slot. Native callbacks must restore
temporary fixity afterwards. Additional provider-owned fixed numerical inputs
must be accounted for in its interface or configuration, rather than allowing
unexplained output fixations to bypass the public rule.

After a fidelity change, rediscover canonical inputs and resolve the pairs
against the new implementation. Retain physically meaningful stable paths where
possible; report pairs whose target or canonical input no longer exists or has
become defined. Do not silently repoint a replacement to some other free input.

Dynamic initial conditions require a separate explicit scope. The present
`initial_values` convention can fix state/rate outputs, so it does not automatically
satisfy the new rule. Before extending enforcement to dynamics, define canonical
initial-condition slots from the dynamic formulation and pair alternative initial
quantities with those slots. An initial condition is not a whole-trajectory input.
The first implementation should cover steady operating specifications and local
steady initialisation, with this dynamic extension recorded as unresolved rather
than silently exempting initial fixes.

## Implementation priority

1. Expose canonical input discovery and implement the slot table and replacement
   mapping in specification parsing/application.
2. Add a fixation audit and a human-readable explanation for direct and replacement
   specifications. Update examples that currently fix outputs without pairs.
3. Make selection and local initialisation preserve the same slot ownership,
   while retaining their existing policies for choosing admissible fixes.
4. Demonstrate temperature instead of enthalpy and compressor outlet pressure
   instead of its selected formulation's input, including save/reload of the pairs.

Tests should concentrate on this contract: accept a direct unsupplied input,
require a pair for an output or supplied input, reject duplicate slot ownership,
retain equations, and show the canonical input remains free under replacement.
Check that invalid documents leave fixity unchanged and that initialization
restores the final specification after temporary closures.

Jacobian rank/conditioning studies can remain a later diagnostic experiment.
The existing structural diagnostics and solver outcomes still describe whether
a particular case works; they do not need to become a new validation framework
before implementing physically explainable variable replacement.
