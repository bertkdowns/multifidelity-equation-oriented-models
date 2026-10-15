# Shared-state heat exchanger design

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

Specification-mode checks and Dulmage–Mendelsohn structural diagnosis are
deferred to future work.

## Ownership and equations

The parent is an IDAES `UnitModelBlockData`. It constructs four thermodynamic
state blocks, ports into those states, area, U, length, and a common heat-duty
expression. Different hot and cold property packages may be supplied.

The lumped formulation adds stream material balances, equal inlet/outlet
pressures, overall energy conservation, and an LMTD heat-transfer relation.
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
initial implementation is steady state, with no pressure drop, reactions,
holdup, or phase equilibrium. Numerical validation uses single-phase liquid BTX.

## Fidelity interface

```python
class MyFidelity:
    def build(self, block, shared):
        # Add private variables and equations to block.
        # Use shared inlet/outlet states, area, U, length, and heat_duty directly.
        ...

    def initialize(self, block, shared, *, solver):
        # Seed private states and initialize the selected equations.
        # Return Pyomo solver results.
        ...
```

Builders are supplied in a name-to-builder mapping. `SharedHX` is a frozen
container of the physical interface, not a copy of its variables. Fidelity
builders must not retain model-specific state on themselves; use their supplied
block so builders can be reused and models can be cloned safely.

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
