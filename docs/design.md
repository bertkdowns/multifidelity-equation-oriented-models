# Shared-state heat exchanger design

These design principles serve the [research purpose](../research-ideas/README.md): initialization
through fidelity changes and selective refinement. Implementation complexity
should be justified by those aims.

## Core principles

1. **Consistent physical meaning.** Every public quantity has the same meaning,
   units, and sign convention in every fidelity. Heat duty is positive heat
   gained by the cold stream and is defined once from its boundary enthalpy flows.
2. **Consistent public degrees of freedom.** Each formulation requires the same
   number of independent public specifications. Internal states and equations
   may differ. The normal fixed specifications remain unchanged across switches.
3. **Preserved specifications.** Selecting a fidelity changes block activation
   only. It preserves all public values and fixation flags and performs no solve.
4. **Single ownership.** The parent owns public states and design variables.
   Fidelity equations use those actual variable objects, including spatial
   endpoints. There are no duplicate public variables, synchronization steps,
   or public-to-private equality constraints.
5. **Private formulation details.** Each fidelity owns its equations, internal
   states, discretization, and initialization guesses inside its own Pyomo block.
6. **Small interface, explicit physics.** The parent integrates with IDAES;
   fidelities are ordinary equation builders with `build()` and `initialize()`.
   Avoid a general lifecycle framework, registries, or speculative abstractions.
7. **Test contracts through integration.** Verify connected solves, physical
   conservation, equal DOF under common specifications, and recovery from failed
   initialization. Do not test internal layout or helper-call sequences.

## Model libraries and research cases

Generic fidelity assembly, selection, and its typed protocol live in `base.py`.
Equipment models live in `unit_models/<unit_name>/` and properties in
`property_models/`. Shared stream helpers belong with the unit-model library.
Equipment-specific interfaces and physics must not leak into the generic mixin.
The top-level package exports the main models for convenient imports.

`case_studies/` owns reconstruction assumptions, reference data, starting
guesses, experimental solve strategies, and written conclusions. The first case
is the [SGHP source loop](../case_studies/sghp/README.md). Research-specific
nominal values are set by the case, rather than hard-coded in library models.

## Specifications and structural diagnosis

Length remains a public variable and is normally fixed in both formulations.
The lumped formulation does not use it. The distributed formulation uses it
to express cell length and area per unit length; with prescribed total area
and U, physical length cancels from the heat-transfer prediction.

Do not add fake equations for unused variables. An initial guess is not a
specification. Equal DOF does not imply that every possible selection of fixed
variables determines a solution. In particular, these thermal models cannot
determine length from thermal performance. IDAES's DOF utility counts variables
appearing in active equalities, so a completely unused free public variable may
not appear in that diagnostic. Integration tests compare DOF with geometry fixed
and with the common thermal design variables released.

General specification-mode checks remain deferred. The complete SGHP case
study now uses Dulmage–Mendelsohn decomposition for determinacy checks and
strongly connected equation groups for experimental group switching.

## Ownership and equations

The parent is an IDAES `UnitModelBlockData`. It constructs four thermodynamic
state blocks, ports into those states, area, U, length, and a common heat-duty
expression. Different hot and cold property packages may be supplied.

The lumped formulation adds stream material balances, specified pressure drops
(zero by default), overall energy conservation, and an LMTD heat-transfer relation.
It uses the smooth log-mean approximation used by IDAES (Kazi et al., 2020),
which is defined at equal terminal temperature differences. Terminal differences
must have the same sign; temperature-crossing cases are outside its domain.

The distributed formulation adds countercurrent finite-volume balances.
Hot flow runs from x=0 to x=1, cold flow in the reverse direction. Each cell
uses the average of its endpoint temperature differences. Only interior states
are private: the first/last states are the parent's states themselves. This
is a spatially discretized 1D formulation, not the previous IDAES collocation
model. Increasing `finite_elements` refines the mesh.

Common property helpers construct states and express stream balances; they do
not own a second representation of the equipment. Property packages must expose
temperature, pressure, state variables, and material/enthalpy flow terms. The
implementation is steady state, without reactions or holdup. The complete SGHP
study additionally uses phase-capable PH properties and specified pressure drops.
Its `ChenHX` and `SegmentedHX` builders add bounded lumped and implicit mixed-cell
closures; see [the study](../case_studies/sghp/FULL_STUDY.md).

## Fidelity interface

`MultiFidelityMixin` supplies `build_fidelities(builders, shared)`,
`select_fidelity(name)`, and `active_fidelity`. Equipment models inherit it
alongside their Pyomo/IDAES base and explicitly call `build_fidelities()` after
constructing their public physical interface. The mixin creates the named blocks,
calls each builder, and selects the first fidelity. It treats `shared` as opaque
and leaves physical state construction and initialization to the equipment.
It does not override the equipment's `build()` lifecycle.

```python
class MyFidelity:
    def build(self, block, shared):
        # Add private variables and equations to block.
        # Use shared inlet/outlet states, area, U, length, and heat_duty directly.
        ...

    def initialize(self, block, shared, *, model, solver):
        # Seed private states and initialize the selected equations.
        # Return Pyomo solver results.
        ...
```

Builders are supplied in a name-to-builder mapping. Valve and exchanger builders
receive their parent `ValveData` or `HeatExchangerData` directly. They access its
public physical attributes (`inlet_state`, `hot_inlet_state`, geometry, and so
on), and obtain time from `parent.flowsheet().time`. There is no separate shared
reference container or field mapping. Concrete parent annotations use
`TYPE_CHECKING` imports to avoid runtime import cycles.

Builders must not retain model-specific state on themselves; use their supplied
formulation block so builders can be reused and models can be cloned safely.

The generic `Fidelity[SharedT]` protocol lives with `MultiFidelityMixin` in
`base.py`. Initializers receive their solve target explicitly as `model`, which
can be an equipment model or a property state block. Solver arguments use Pyomo's
existing `OptSolver` type. Equipment builder mappings are typed with their parent
model; property builders receive `WaterStateData`, accessing constants and
configuration through `state.params`. All use type-only imports where needed.
The mixin treats the supplied object as opaque and does not depend on equipment
or property interfaces.

During initialization the parent temporarily fixes inlet and design variables
at their current values, supplies feasible boundary temperature guesses when
needed, and delegates to the selected builder. Temporary fixations are restored
even when the solver raises or returns unsuccessful termination. Values may
change on failure. Built-in formulations do not temporarily deactivate equations
or call the old IDAES heat-exchanger initializers. A future initializer that
changes flags is responsible for restoring its changes in `finally`.

The caller owns solving the complete flowsheet, choosing fidelities, fallback
policy, and accuracy assessment. Initialization uses current inlet values; a
flowsheet initializer must initialize upstream equipment first.

Fallback can deliberately retain a coarser model when appropriate to the
research question. Acceptance under that model must be distinguished from
validation of the detailed equations. The valve library therefore offers both
a tangent approximation and a basic shutoff-capable correlation; experiment
policy, rather than the mixin, decides whether fallback is acceptable.

## Property fidelities

The same ownership and selection principles apply to properties. The water
parameter block owns constants and builder configuration; every water state
block owns flow, temperature, pressure, and the public property variables.
Linear and Helmholtz builders add equations using those same objects. Phase
property aliases and enthalpy-flow terms are defined once outside the fidelity
blocks, so existing unit equations remain connected across switches.

See [water.md](water.md) for the equations, scope, and runnable example.

## Flowsheet-level selection

`workflow.py` supplies small research searches over named `FidelityChoice`
objects. Equipment remains responsible for equations; a solve callback supplies
numerical acceptance, cost, and diagnostics. Refinement rolls failed candidates
back to the last accepted state and assignment. Relaxation retries from the
original guesses after ranking a failed point. Policies and validity checks
belong to the case study, not the assembly mixin. Greedy searches do not imply
global optimality or physical accuracy.
