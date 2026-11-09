# Canonical variables and specification replacement

Research and implementation note, investigated 6 November 2026 and revised
9 November 2026.
This note connects [pyomo-replace](https://github.com/bertkdowns/pyomo-replace)
to the current [specification study](information-directed-specification.md) and
[initialisation proposal](initialisation.md). The specification format, structural
pairing, application checks and slot-aware initialisation below are now implemented.
The broader research experiments and dynamic initial-condition pairing remain
future work.

The public API is `canonical_inputs()`, `pair_specification()`,
`apply_specification()`, `specification_slots()` and `audit_fixations()`.
`select_specification()` keeps its trust-ranked DM policy and adds automatic
pairs to the returned document; an unresolved assignment appears in
`pairing_error` and prevents `complete=True`. Examples have been migrated to
explicit replacement mappings. The model viewer accepts those mappings in saved
result specifications. Historical result snapshots retain their original metadata.

## Purpose and core rule

The main advantage is a physically understandable explanation of how a model is
specified: **we fix temperature instead of enthalpy at this point**, or **we fix
compressor outlet pressure instead of compressor work**. The model records which
normal input is now calculated, rather than leaving that choice implicit in a
list of fixed measurements. Numerical conditioning is a separate concern and is
not the motivation or a prerequisite for this implementation.

The implementation uses general mathematical and graph logic only. It does not
recognise thermodynamic states, compressors, or particular kinds of quantities.
Variable names, descriptions and units make the resulting pairs understandable
to the user; they do not determine which pairs the algorithm permits or prefers.

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
Keep the existing direction and duplicate-definition checks. Discover replacement
candidates automatically from the equation incidence graph and DM/matching
analysis. No model-authored list of permitted replacement pairs is required.
Use locality and graph distance to choose a readable explanation among admissible
candidates; the user can edit that choice later.

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

### Implemented JSON format

Retain the existing record-ID arrays and add one `replacements` object. Its keys
are selected information-record IDs; its values are the canonical input paths
those records replace. This is the serialized format, not just a display
of the generated explanation:

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

| Field | JSON type | Meaning | Default |
| --- | --- | --- | --- |
| `specifications` | Array of record-ID strings | Information records whose target variable families are fixed. | `[]` |
| `replacements` | Object mapping record-ID strings to variable-path strings | Canonical input occupied by each noncanonical operating fixation. Omit an entry for a direct canonical fixation. | `{}` |
| `initial_values` | Array of record-ID strings | Existing first-time-slice initial-condition choices; automatic replacement for this scope is deferred. | `[]` |

For a steady-state case, `initial_values` is empty. The `replacements` keys
must occur in `specifications`; this mapping does not yet
describe replacements for dynamic initial conditions. Do not interpret an initial
condition as an operating fixation or silently apply these steady-state rules to
it. The separate dynamic extension described below must specify that contract.

Use root-relative variable-family paths, with no index selectors, consistent with
information records and `get_variable()`. Record IDs and paths are nonempty
strings. Reject unknown top-level fields and replacement IDs absent from the
selected operating records. The mapping's values are variable paths, not IDs of
other information records.

### Information supplied alongside the specification

The specification above is used with an information document such as:

```json
[
  {
    "id": "inlet_pressure",
    "tag": "P-1",
    "information_type": "sensor_reading",
    "variable_path": "state.pressure",
    "type": "constant",
    "value": 200000,
    "unit": "Pa",
    "trust_rank": 9
  },
  {
    "id": "measured_temperature",
    "tag": "T-1",
    "information_type": "sensor_reading",
    "variable_path": "properties.temperature",
    "type": "constant",
    "value": 350,
    "unit": "K",
    "trust_rank": 9
  }
]
```

The selected model supplies variables, equations and canonical-input discovery;
the implementation document supplies the relationship choices. Neither is
embedded in the specification document. Together these inputs resolve to:

| Canonical slot | Fixed target | Information record | Action |
| --- | --- | --- | --- |
| `state.pressure` | `state.pressure` | `inlet_pressure` | Fix pressure to 200000 Pa directly. |
| `state.enthalpy` | `properties.temperature` | `measured_temperature` | Fix temperature to 350 K; leave enthalpy free. |

This table is derived, not another saved field. Values, units, uncertainty and
trust remain in the information document. Pairing scores, alternatives, DM status
and solver results remain separate diagnostics. The specification stores the
chosen records and pairs, whether generated automatically or edited by the user.

### Pairing semantics and compatibility

Application semantics:

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
break the proposed rule. Migration should run the same automatic pairing method
used by selection, save the inferred pairs, and report any unresolved cases. It
should not require users to annotate every existing output fixation manually.

This changes the earlier proposal: the final fixed set alone is insufficient.
An optional audit can still record selection decisions and rejected alternatives,
but the chosen replacement pairs are part of the specification itself.

## Apply and maintain the specification

[`SpecificationDocument` and `apply_specification()`](../src/multifidelity/model_language/specification.py)
use the mapping above. Shared structural pairing and slot validation are in
[`replacement.py`](../src/multifidelity/model_language/replacement.py). Manual
application requires explicit pairs; `pair_specification()` generates missing
pairs without changing the selected record IDs or numerical instance.

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

## General mathematical rule, readable domain examples

Let `C` be the canonical inputs obtained from the selected model's declarations,
and let `z` be a variable chosen for fixation. If `z` belongs to `C`, it occupies
its own slot. Otherwise choose a canonical input `c` using structural exchange
admissibility and the graph/hierarchy heuristic described below. Record the pair
`z replaces c`. The same procedure applies to every model and every variable.

The report can render this as **fix {z}, instead of input {c}**, using the model's
existing labels or paths. It does not need equipment-specific explanation rules.
For example, this generic template might produce:

| Canonical input | Fixed variable | Rendered explanation |
| --- | --- | --- |
| `state.enthalpy` | `properties.temperature` | Fix temperature instead of input enthalpy. |
| `compressor.parameters.pressure_rise` | `compressor.outlet.pressure` | Fix outlet pressure instead of input pressure rise. |

These are illustrations of algorithm outputs, not rules to encode. In particular,
there must be no special case saying temperature replaces enthalpy, pressure
replaces work, or a variable with a particular unit is a preferred partner.
Existing unit conversion still validates each information record against its
own target variable; it does not compare the units of the replacement pair.

Which inputs are canonical follows the selected model, not domain knowledge in
the replacement code. Thus if work is a canonical input, it can be a candidate;
if the equations define work, it cannot be the canonical partner. This falls out
of the same declaration and graph logic, without recognising a compressor or
requiring a new formulation merely to obtain a particular explanation.

The generated pair states a structural specification choice. It does not claim
a unique physical cause or a unique interpretation of the equations. Multiple
mathematically admissible pairings can explain the same selected fixed set.

## Automatic pairing with DM analysis and a locality heuristic

Keep the existing information-driven specification method. It chooses which
information to use; automatic pairing explains which canonical inputs those
choices replace. These are related steps, but the explanation heuristic should
not quietly change the trust ordering or discard a useful measurement merely
because its nearest input already has a partner.

The current [`select_specification()`](../src/multifidelity/model_language/selection.py)
tries records in trust order and uses DM analysis to accept structurally useful
fixations. Its result now includes the replacement mapping. The user does not
need to supply candidate pairs, and model definitions do not gain a replacement
catalogue.

### Structural candidates

Build the bipartite graph of active equality equations and concrete variable
entries, including connections and provider equations. Retain isolated variables
in the analysis. Canonical status comes from the declarations; structural
connectivity comes from the equations.

For a proposed noncanonical fixation, identify canonical inputs connected to it
through this graph. Use maximum matching and the corresponding DM deficiency counts to
find admissible exchanges in the context of the other selected specifications.
A shared connected component is a useful first filter, but not sufficient on its
own. Likewise, two variables appearing somewhere in the DM underconstrained
partition does not by itself make them an exchange pair. The actual exchange
must preserve the intended structural matching.

A simple prototype can test candidate exchanges on a structural working copy:
use the canonical closure as a reference, release the candidate canonical input
and impose the proposed fixation, retaining the other chosen exchanges. Compare
matching/DM before and after. Where a valid canonical reference closure exists,
the exchanged closure must remain structurally complete. Some steady reductions
of dynamic models have a deficient canonical reference: for example, level may
replace a withdrawal input whose value is constrained by zero accumulation.
The implemented trial allows an exchange to improve deficiency and unmatched-row
counts, but never worsen either. This is general matching logic, not a tank rule. More efficient
alternating-path queries can replace repeated trials later.

These reference fixations are graph bookkeeping: no canonical measurement or
numerical value is needed, and they are never applied to the operating instance.
The existing selector still returns a partial plan when information is missing.
Actual structural completeness is still reported by the selector, separately
from the replacement explanation. Virtual reference closure must not be confused
with sufficient measured information for the operating instance. Jacobian
validation is not part of this pairing procedure.

### Rank the admissible partners

Among structurally admissible choices, use a simple deterministic ordering:

1. Prefer an input belonging to the same model occurrence as the fixed quantity.
   Otherwise prefer a nearby occurrence in the hierarchy, measured by distance
   through their lowest common ancestor.
2. Prefer a shorter equation/variable path between the canonical input and the
   fixed quantity. Count equation crossings consistently, including connections.
3. Use upstream position as a secondary preference where the declared connection
   directions or `determines` dependencies provide a useful ordering.
4. Break remaining ties by the canonical variable's root-relative path.

This ordering uses only model ownership, graph distance and declared edge
direction. It never inspects variable names, physical quantity categories or
equipment types. The structural check first determines which choices are possible
under the other specifications; the heuristic ranks those choices. Domain examples
may illustrate the result but must not add exceptions or override this ordering.

Upstream preference is optional and must not exclude otherwise admissible pairs.
Equations remain implicit and recycle loops need not have a unique upstream
ordering. We can start with locality and distance, then assess whether adding an
upstream tie-break improves explanations on actual flowsheets.

### Preserve existing selection behaviour

The implementation runs the current trust-ranked selector, then pairs its
chosen noncanonical targets with canonical inputs. Direct canonical fixations
reserve their own slots. Find an injective assignment of the remaining targets
to admissible canonical slots, and validate the whole assignment structurally.
This post-processing route preserves the selected information set while adding
the replacement explanation.

Do not commit permanently to the first greedy pair. A later specification can
require moving earlier pairs. Recompute pairing for the entire chosen set, reserving all direct inputs first
and honouring explicit user pairs as a joint assignment. This allows a later
direct record to move an earlier automatic pair to another slot. Future
alternating-path or search methods can extend this bounded heuristic if a valid
assignment cannot be found. A matching over
independently generated candidate pairs is only a proposal until the combined
closure has been checked. If no assignment can be found, return the selected
records with an explicit unresolved-pair diagnostic rather than inventing a pair
or silently changing the chosen information. Such a result is not yet ready for
application under the replacement rule.

Pairing can subsequently be integrated into each DM selection trial, allowing
reassignment after an accepted record. Neither approach changes the existing
achieved-setpoint policy, prediction-target exclusions or unit/value checks.

### User overrides and explanations

Save the generated pairs in the specification document. The main report shows
**what is fixed, which input it replaces, where both quantities belong, and which
information record supplies the value**. Separate diagnostics can record why the
heuristic preferred that input and list alternative admissible partners.

The user can switch partners, including swapping several pairs together, without
changing the measured values or physical equations. Validate the edited assignment
jointly for connectivity, structural admissibility and unique slot ownership.
Accept any admissible user choice even when the heuristic prefers another one.
Changing pairs alone need not change numerical fixity: when the selected fixed
variables stay the same, it changes their explanation and slot ownership. If the
user changes the fixed targets as well, apply the fixation update atomically.

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
against the new implementation. Retain admissible pairs where possible and
rerun automatic pairing for affected choices, reporting any changes. User-pinned
pairs that become invalid need an explicit diagnostic rather than a silent
replacement by the heuristic.

Dynamic initial conditions require a separate explicit scope. The present
`initial_values` convention can fix state/rate outputs, so it does not automatically
satisfy the new rule. Before extending enforcement to dynamics, define canonical
initial-condition slots from the dynamic formulation and pair alternative initial
quantities with those slots. An initial condition is not a whole-trajectory input.
The implementation supports whole-family operating replacements on steady or
finalized dynamic grids, and local steady initialisation. Initial conditions
remain explicitly tracked first-slice fixes in their own scope; automatic pairing
of those initial conditions is deferred.

## Implemented scope and verification

- Canonical input discovery, replacement document parsing and atomic application.
- Structural candidate trials, hierarchy/distance ranking and explicit user overrides.
- Automatic pairing after information selection, with separate unresolved-pair diagnostics.
- Slot reports and fixation audits, including protection of replaced inputs during
  local initialisation when their fixed targets are in the active subtree.
- Migrated SGHP and tank examples, provider-backed replay specifications and
  model-viewer support for the new specification metadata.
- Generic algebraic tests for pairing, reassignment, invalid exchanges, scope,
  slot ownership, clone behaviour and save/reload.

Tests should concentrate on this contract: accept a direct unsupplied input,
require a pair for an output or supplied input, reject duplicate slot ownership,
retain equations, and show the canonical input remains free under replacement.
Check that invalid documents leave fixity unchanged and that initialization
restores the final specification after temporary closures. Include automatic
pairing cases with a local and a distant admissible partner, a connected but
inadmissible exchange, and a later record that requires reassignment of an earlier
pair. Verify that a valid user override is accepted and that changing only pairs
leaves the numerical fixed set unchanged. Renaming quantities or changing their
physical labels must not affect admissibility or locality/distance scores; only
the documented deterministic path tie-break may change when paths are renamed.

Jacobian rank/conditioning studies can remain a later diagnostic experiment.
The existing structural diagnostics and solver outcomes still describe whether
a particular case works; they do not need to become a new validation framework
before implementing physically explainable variable replacement.
