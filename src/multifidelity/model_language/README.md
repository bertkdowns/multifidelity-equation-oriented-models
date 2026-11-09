# JSON model specification language

This is an implementation of the model language discussed
for recursive multifidelity modelling. It builds a selected equation hierarchy
inside an **IDAES** `FlowsheetBlock`, using Pyomo blocks, variables and constraints.
The builder does not solve; declared defaults supply unfixed starting guesses. Specification documents can
be applied separately to fix values from an information document.
Construction leaves all public variables free, with values only where defaults are declared. Operating
specifications and initial conditions are both applied through `apply_specification()`.
Here "build" means creating Python modelling objects, not numerical initialization.

Relationships can also use registered Python providers to construct symbolic
Pyomo/IDAES models behind the same public structs. See the
[custom-model how-to guide](custom-models.md) for registration, variable mappings,
dependency declarations, and composition with replaceable property models. A
runnable example is in [`examples/custom_models`](../../../examples/custom_models).

The [standard symbolic model library](standard-models.md) supplies Helmholtz and
humid-air property wrappers, an extracted EN 12900 compressor map, and a JSON
compressor composition. Call `register_standard_providers(library)` before building
their external relationships, or use the CLI's `--standard-providers` option.

## Property-package configuration decision

The earlier shared-binding blocker is resolved for the current use case through
configured package wrappers. The heat pump keeps flow, pressure and enthalpy on
its public stream interface. Temperatures and property coefficients remain inside
its selected relationship's property models.

`water_property_package` wraps `water_state_ph` and determines all eight coefficient
inputs with constant equations. Each occurrence has its own coefficient variables;
shared coefficient identity is not required. These inputs are excluded from
`required_inputs()` because the wrapper supplies them. The construction-only
backend does not call `.fix()`: coefficients are constrained to constants and may
still appear in solver equations until preprocessing eliminates them.

A separate shared-binding mechanism is not needed to continue this integration.
The Carnot-efficiency relationship remains future work.

## Why a separate specification language?

This language expresses reusable mathematical definitions as data, so a model's public interface can stay stable while alternative internal formulations are selected recursively.

JSON is the source of truth: one file per reusable model, readable and reviewable
in Git. Model IDs are independent of filenames. No database is required. A future
editor or SQLite index can operate on the same conceptual definitions.

This language is the repository's primary modeling approach. Custom Python providers may supply symbolic implementations behind the same JSON interfaces. The language uses the vocabulary and ownership below, including separate boundary variables joined by equations in composites.

## Vocabulary and ownership

The authoritative [model-language glossary](terminology.md) defines all document,
implementation, information, specification and numerical-instance terms.

Models are reusable types. Two references to `heat_exchanger` do not copy its JSON
definition, but construction creates distinct variables for each occurrence.
Only one relationship participates per occurrence. All model references within
that selected relationship participate together. Unselected relationships create
no Python components and require no selections.

Deleting a relationship deletes its owned references and equations, not the
referenced model definitions. Deleting an owned struct deletes its variables.
References never imply ownership.

All structs on a model are public to its own relationships and to the containing
relationship. Internal models are encapsulated by the relationship containing
them: callers cannot reach through a child to its grandchildren. Relationships
own no variables. Extra internal quantities must be declared on a model's struct,
possibly on a dedicated internal model referenced by the relationship.

## Typed definition documents

`definitions.py` defines Pydantic types matching the JSON definitions. They can
be parsed and navigated without constructing solver objects:

```python
from pathlib import Path
from multifidelity.model_language.definitions import ModelDocument

model = ModelDocument.model_validate_json(Path("my_model.json").read_text())
model.structs["inlet"].variables["pressure"].unit
model.relationships["basic"].models
```

`Library` loads every JSON document into these types. Both `library.models["valve"]`
and `library.get("valve")` return a `ModelDocument`, and the builder consumes its typed
structs, relationships and reference variants directly. Definition documents retain model IDs and generic references for serialization.
Model-view navigation is supplied separately by `resolution.py`; it does not unroll
a tree or select implementations.

Document-shape validation rejects unknown fields, invalid component names,
missing required fields, unsupported variable types, invalid directions and
ambiguous reference kinds at load time, including in unselected alternatives.
Scope, generic interface compatibility, dimensions supported by the backend,
equation units and determination checks remain in the builder and apply to the
selected implementation. Implementation documents have typed selection classes, described below.
Serialize definitions with `model_dump(by_alias=True)` or
`model_dump_json(by_alias=True)` to preserve JSON names (`Connection.from_` in
Python is `from` in JSON). Instance types remain deferred; implementation types are described below.

## Model-view navigation

`resolution.py` owns library loading, model-reference resolution and generic
interface checks. `builder.py` consumes these same model views when constructing
Pyomo objects; it no longer contains its own generic resolver.

```python
from multifidelity.model_language.resolution import Library

library = Library()
root = library.resolve("water_state_block")
block = root.relationships["evaluate"].models["states"]
fluid = block.relationships["evaluate"].models["fluid"]
fluid.id  # "water_property_package"
fluid.structs["state"].variables["pressure"].unit  # "Pa"
```

`ModelView.definition` is the shared typed JSON definition. Its `structs` and
its relationships' `constraints`/`connections` expose those same definition objects.
The `models` collection maps local aliases directly to model
views; each carries the generic arguments and path for its own reference context.
There is no per-reference `resolve()` call and no solver construction involved.

Relationship children are resolved on first access, then cached on that view.
This allows recursive definitions without eager unrolling and keeps unused
alternatives from forcing unrelated references to resolve. Errors in references
or generic interfaces surface when the corresponding children are accessed.
The builder accesses only its selected relationship at each level.

Treat definitions as unchanged while using a model view. After editing the
library, call `library.resolve(...)` again to obtain a fresh view. Model views
are navigation objects, not simulation instances: repeated references share their
definition, while the backend still creates distinct solver variables per occurrence.

Unit compatibility uses Pint here, without importing Pyomo in the resolution
module. Equation compilation, determination checks and Pyomo-specific validation
remain in the builder. Root generics remain unsupported.

## Documents

A model contains `id`, optional `description`, `structs`, and `relationships`:

```json
{
  "id": "valve",
  "domains": {"time": {"kind": "time"}},
  "structs": {
    "inlet": {
      "direction": "input",
      "variables": {"pressure": {"unit": "Pa", "dimensions": ["time"]}}
    },
    "outlet": {
      "direction": "output",
      "variables": {"pressure": {"unit": "Pa", "dimensions": ["time"]}}
    }
  },
  "relationships": {
    "no_pressure_drop": {
      "models": {},
      "constraints": {
        "pressure": {
          "for_each": {"t": "time"},
          "lhs": "outlet.pressure[t]",
          "rhs": "inlet.pressure[t]",
          "determines": "outlet.pressure[t]"
        }
      },
      "connections": {}
    }
  }
}
```

Variable declarations support `unit` (default `dimensionless`), `value_type`
(currently only `real`) and `bounds: {"min": ..., "max": ...}`. Bounds are numerical
values in the declared unit. An optional finite `default` supplies a starting
guess in that same unit, within the bounds. It broadcasts over all index entries,
including entries added during discretization. Omitted defaults leave values unset.
All variables start free during construction.
Variables may declare ordered named `dimensions`; see indexed models below.
Input/output describes struct direction, not fixed/free solver status. A default
does not specify a model or fix an input.

For example: `{"unit": "Pa", "default": 200000, "dimensions": ["time"]}`.
An optional `scale` is a finite, strictly positive multiplicative scaling factor:
`{"unit": "Pa", "default": 200000, "scale": 1e-5}` gives a scaled coordinate
of 2. Missing scales default to 1, independently of guesses. Index entries share
the declaration's scale, including entries added by discretization. Bundled
models carry illustrative characteristic-magnitude scales in their declarations;
these are not inferred from the current value at runtime.
Defaults in the bundled state/property models are illustrative guesses, not
validated operating points or mutually consistent thermodynamic states.

After applying a specification, call
`apply_starting_values(model, information, specification)` to seed free public
variables from unused information records. The highest trust rank wins, with ID
as the deterministic tie-breaker. Values are converted to the variable's unit;
constants broadcast and series must match the current grid. Applicable guesses
are validated before any values change. Fixed entries are preserved, selected
specification/initial-condition records are excluded, and paths absent from the
selected implementation are ignored. Use `excluded_record_ids` for held-out
measurements or other records that must not influence initialisation. A control
setpoint used this way is only a guess, not evidence that the setpoint was achieved.
The function returns the IDs used and never fixes variables. Information guesses
override declaration defaults; no separate initial-guesses document is needed.
The existing specification `initial_values` list still means fixed dynamic
initial conditions, not solver guesses.

Custom providers may register an optional initialisation callback; see
[custom initialisation](custom-models.md#optional-initialisation-callback).
Neither building a model nor applying specifications invokes these callbacks.

### Bottom-up steady-state initialisation

After applying the operating specification, call:

```python
from multifidelity.model_language import initialize_model

result = initialize_model(
    model, solver=solver, information=information, specification=specification,
)
```

The optional information arguments seed unused records; trust breaks numerical
ranking ties. They do not apply operating specifications. Finalise the grid first;
multiple steady time points are supported, but dynamic initialisation is not.

The initializer visits selected model occurrences in postorder, treating native
providers as leaves. For each local subtree it preserves existing specifications,
then trial-fixes one free boundary input entry to its current finite, in-bounds
value. DM first identifies eligible boundary inputs. The initializer evaluates
the Jacobian in scaled variable coordinates, normalises equation rows to unit
infinity norm, and uses SVD to find its null space. Eligible inputs are ranked
by their squared row norm in an orthonormal null-space basis: their participation
in the remaining freedom. Scores within the rounding precision of 12 decimal
places tie; higher information trust, then path/index break ties. It recomputes
DM and numerical scores after each accepted fix. Trials must reduce structural
deficiency without overconstraint. In addition to the current occurrence's own
inputs, eligible candidates include descendant public inputs that are not
supplied by their immediate parent's incoming connections, defining constraints
or derivatives. Parent-supplied inputs remain eligible at their own local stage,
where the parent equations are outside the problem, but not at ancestor stages.
This rule applies recursively and never admits outputs or native internal
variables. Merely forwarding an input as a source does not define that input.

Registered callbacks run only at their own provider occurrence. If the equations
are not already satisfied, the configured solver completes the local solve.
Temporary fixes are released before the parent stage; solved values remain as
guesses for the larger coupled problem. The root receives no temporary fixes
and is solved under the original operating specification.

The result contains `success`, `failed_model`, used starting-value record IDs,
and a `stages` list with structural deficiency, temporary fixes, missing/invalid
guesses, callback names, solver termination and residual checks. Numerical
evaluations record candidate scores, structural versus numerical rank, singular
value extremes and rank thresholds. The result also records native scaling
callbacks and variables assigned fallback-derived scales during that scaling pass. Initialisation
stops at the first failure. That stage's values are restored, while values from
earlier successful children remain. Original fixed values, fixity and constraint
activation are restored on success or failure. Failed solver iterates are never
retained as successful initialisation.

Missing free-variable guesses are reported; derived unknowns may still be found
by a solver. A missing or invalid guess cannot be used as a temporary boundary
fix. Nonfinite or out-of-bounds existing values prevent a local solve. Structural
completeness does not guarantee numerical feasibility. Final variable values and
equations are checked even after a reported solver success. The default residual
tolerance is `1e-6` on scaled equation residuals. `max_constraint_violation` retains
the raw mixed-unit diagnostic; `max_scaled_constraint_violation` reports the
quantity used for acceptance. Use `residual_tolerance` to change the threshold and `tee=True`
for solver output. Aggregate-first transfer and numerical recovery remain future
work; a failed stage is returned for inspection without changing its fidelity.

Scaling callbacks run once before local traversal. Row factors are recomputed at
each Jacobian evaluation and after local closure; they remain fixed during that
solve. Local IPOPT solves use the same multiplicative suffix factors through
`nlp_scaling_method=user-scaling`; physical variables and authored equations are
not transformed. Alternative solvers must support the scaling suffix convention.
`apply_scaling(model)` can also be called explicitly for variable/provider scales;
it returns a `ScalingReport` and never fixes or solves variables.

The default `rank_tolerance=1e-10` is relative to the largest singular value.
Numerical rank below the DM structural rank stops the stage explicitly, rather
than creating extra fixes. Invalid derivatives or missing nonlinear state guesses
produce diagnostics. Derivatives use Pyomo reverse symbolic differentiation and
native external-function derivatives; PyNumero is not required. Piecewise
`Expr_if` expressions are differentiated on the currently selected branch, so
phase transitions, branch changes and poor starting points remain limitations.
Dense SVD targets bounded local models; it is not a large-flowsheet sparse method
or a guarantee of an optimal fixed-variable subset.

### Equations and connections

Constraints have `lhs` and `rhs` expression strings and always mean equality.
Each constraint also requires a `determines` variable reference.
There is no separate expression object, assignment, or `solves_for` hint. Derived
quantities are variables with defining equations. Supported arithmetic is
`+`, `-`, `*`, `/`, `**`, unary signs, numeric literals and parentheses.
References are `struct.variable` or `child_alias.struct.variable`. Dimensioned
constants use explicit unit literals, for example `298.15 * units.K` or
`4180 * units.J / units.kg / units.K`. The `units` namespace allows only a
single public unit name, not method calls or nested attribute access. Existing
variable references take precedence over unit literals. Units use
Pyomo unit names, for example `kg/s`, `J/kg`, `W/K`, and `dimensionless`.
`determines` is a validation contract, not an assignment or optional solver hint.
Its target must be a parent output or an immediate child input. It must occur
in the equation directly, or influence it through already validated descendant
equations and connections. Local declarations cannot justify one another through
a dependency cycle. This is a structural dependency check, not proof of nonzero
sensitivity or mathematical determinacy. It may appear on either side or inside an arithmetic expression.
For example, a balance `outlet.flow * outlet.enthalpy = ...` can determine
`outlet.enthalpy`. Parent inputs and child outputs cannot be targets here.

**Each output is determined exactly once.** Each selected relationship must
determine every parent output exactly once.
Connections implicitly determine every variable in their destination struct and
share the same determination registry as explicit constraints. Two constraints,
two connections, or a constraint and a connection targeting the same variable
are rejected with both source names. Missing outputs are listed together.
Validation is local to each selected relationship and is repeated recursively;
unselected alternatives do not undergo determination validation during a build
(their document shape is still validated when the library loads).

Child inputs without a determination are permitted: they remain specifications
for a future instance to supply. This check neither fixes them nor proves that
outputs can be calculated: cycles, dependent equations, singularities and multiple
solutions require further analysis. Required inputs can be listed using the methods described below.

Python calls, imports and arbitrary code are not supported; expression
strings are parsed using a restricted AST interpreter, never `eval`.

### Named domains and indexed algebraic equations

Models declare index domains, while numerical members belong to build
configuration. No variables are fixed or initialized by this configuration:

```json
"domains": {
  "time": {"kind": "time"},
  "components": {"kind": "discrete"}
}
```

Declare a variable with `"dimensions": ["time", "components"]`; an omitted or
empty list still means scalar. Dimensions must be distinct declared domain names.
Domain members are one-dimensional, nonempty ordered sets of finite numbers or
strings. Time points must be numbers in strictly increasing order. A root time
domain defaults to `[0.0]` and uses the flowsheet's actual `time` set. At most one
time domain is allowed at the root. The default `mode="steady"` builds independent
algebraic time slices. `mode="dynamic"` uses a shared continuous time domain and
requires at least two explicitly supplied time points; see derivatives below.

Use explicit loop bindings and subscripts in equations:

```json
"flow": {
  "for_each": {"t": "time", "j": "components"},
  "lhs": "outlet.flow[t, j]",
  "rhs": "settings.factor * inlet.flow[t, j]",
  "determines": "outlet.flow[t, j]"
}
```

Scalar references remain unindexed. Indexed references must explicitly supply
the correct number and order of loop indices from matching domains. Index names
are scoped to the equation and only allowed inside subscripts. Calls, slices,
literal indices, index arithmetic, reductions, and attributes after subscripts
are not supported in this first implementation.

Each `determines` declaration must cover the target's whole indexed family,
with exactly one loop index per dimension and no extra loops. Partial targets
and repeated scalar determinations are rejected. Different loop names cannot
hide duplicate determinations of the same family. Dependency validation is
performed for each constructed variable entry, not only at family level.

Child occurrences explicitly bind their domains to the containing model:

```json
"models": {
  "pipe": {
    "model": "pipe",
    "domain_bindings": {"time": "time"}
  }
}
```

Binding keys are child domain names and values are parent domain names. Names
may differ, but kinds must match. Every child time domain requires a binding;
bound domains reuse the very same Pyomo set. Discrete domains may instead be
local to an occurrence. Two local sets with identical members do not imply a
shared domain. Bindings are also supported on `model_parameter` references.

Connections expand field by field and index by index, retaining unit conversion.
They require matching ordered domain signatures after binding; there is no
implicit scalar broadcasting or grid interpolation. A scalar can still be used
explicitly in an indexed equation, as `settings.factor` is above.

```python
model = build_model(
    "network", implementation, library=library,
    domain_values={
        "time": [0, 10, 30],
        "components": ["water", "salt"],
        "network.pipe.cells": [0, 1, 2],
    },
)
```

Root-domain configuration keys are their local names. Unbound child discrete
domains use occurrence-qualified keys (`root_model.child_alias.domain`). Supply
values only for declared, unbound domains in the selected hierarchy; unknown or
unused keys are errors. Bound domains need no separate values.

`required_inputs()` returns one entry per required variable family, retaining
its `dimensions`, without needing numerical domain values. Generic interfaces
continue to compare ordered dimension declarations. External symbolic providers
use one scalar provider instance per time point; see the
[custom-model guide](custom-models.md).

### Library-wide time convention

Every bundled model declares a time domain, including wrappers with no public
structs. Streams, property states and reported properties, performance quantities,
operating efficiencies, pressure changes, split fractions, duties, and setpoints
are indexed by time. Child occurrences explicitly bind to the parent's shared
time domain, and generic requirements use the same ordered dimensions.

Fixed affine-water coefficients (`water_state` and `water_state_ph` parameters),
tank area, pipe geometry/physical parameters, and exchanger conductance remain
scalar. Tank pressure is an operating time series. The configured water wrappers determine their
coefficients once, while evaluating their state/property equations at every time.
Map coefficient arrays and rating configuration remain in provider configuration;
reported rating outputs are time-indexed like the rest of the map interface.

Existing implementation selections and required-input family paths are unchanged.
Python access to operating values now needs an index even in steady mode:

```python
steady = build_model("valve", {"relationship": "isenthalpic"})
steady.fs.root.structs.inlet.pressure[0].fix(200000)

transient = build_model(
    "valve", {"relationship": "isenthalpic"},
    mode="dynamic", domain_values={"time": [0, 60]},
)
```

A valve, pump, or property model with no accumulation still contributes
instantaneous algebraic equations inside a dynamic flowsheet. It does not gain
holdup, delay, or a derivative merely by sharing continuous time. Multiple points
in steady mode remain independent operating points.

The [PI controller](pi-controller.md) provides ideal tracking and dynamic PI
relationships using normalized signals.

The library examples, including `pipe` and `tank`, demonstrate time-indexed variables.
Spatial derivatives and indexed collections of child occurrences remain future
work.

### Derivative relations and steady/dynamic construction

Relationships can declare first-order derivative relations alongside their
ordinary constraints and connections:

```json
"derivatives": {
  "level": {
    "kind": "derivative",
    "state": "inventory.level",
    "rate": "rates.level",
    "with_respect_to": "time",
    "determines": "inventory.level"
  }
}
```

`kind` defaults to `derivative`. State and rate are whole local variable paths,
without subscripts. Both must have the same ordered dimensions, including the
declared time domain. The relation covers the whole family. Put a derivative in
a reusable child model and connect its input/output structs to compose it with
other models; reaching into child variables from a derivative declaration is not
supported. Only one derivative of a given state with respect to time is allowed
per selected relationship.

**Each output is determined exactly once.** A derivative relation participates in
the same registry as equations and connections. It may determine its state
(integration) or its rate (differentiation). A balance equation can separately
determine the rate when the derivative relation determines the state. Duplicate,
missing, input-directed, or unrelated derivative targets are rejected.

The same definition and implementation can be rebuilt in two modes:

| Mode | Time set | Derivative relation |
| --- | --- | --- |
| `steady` (default) | Ordered set; defaults to `[0.0]` | Rate equals zero at every operating point |
| `dynamic` | IDAES shared `ContinuousSet` | Pyomo `DerivativeVar` linked to the declared rate |

Time coordinates use `time_unit="s"` by default. Both state/rate units and the
time unit are validated; conversions such as minutes to seconds or J/s to kW
are supported. The backend introduces a private derivative with respect to the
numerical time coordinate and includes the physical time unit in its public-rate
binding. This also keeps Pyomo-generated discretization equations unit-consistent.
Public variables are still owned by their declared structs.

Steady construction does not choose inventory levels or other unconstrained
operating specifications. It also does not silently discard conservation
equations. For a steady tank, specify the level and allow a flow to be calculated
from mass conservation rather than fixing both flows independently. Rebuilding
does not transfer values between models automatically.

### Initial specifications

`required_initial_values(model_id, implementation, library=...)` returns the
root-relative output family of each selected derivative relation. This is the
default authoring convention: supply an initial value for what the derivative
relation determines. Families with other dimensions need a starting profile.
It describes specification requirements, not DAE index or numerical solvability.

Initial values belong to instance data, not model definitions or implementation
selections. They are selected by the `initial_values` list of a specification
document, alongside ordinary `specifications`. Both lists contain information-record
IDs; paths, values, units and uncertainty stay in the information document.

```python
from pathlib import Path
from multifidelity.model_language import (
    build_model, required_initial_values, InformationDocument,
    SpecificationDocument, apply_specification,
)
from pyomo.environ import TransformationFactory

selection = "examples/model_language/tank_mixed.json"
print(required_initial_values("tank_flowsheet", selection).keys())
# tank.inventory.energy, tank.inventory.mass
model = build_model(
    "tank_flowsheet", selection, mode="dynamic", domain_values={"time": [0, 1000]},
)
TransformationFactory("dae.finite_difference").apply_to(
    model, wrt=model.fs.time, nfe=100, scheme="BACKWARD",
)
folder = Path("examples/dynamic_tank")
information = InformationDocument.load_json(folder / "information.json")
specification = SpecificationDocument.load_json(folder / "specification.json")
apply_specification(model, specification, information)
```

`specifications` fixes whole variable families; `initial_values` fixes only the
first time point (`model.fs.time.first()`, which need not be zero). Initial entries
require a dynamic model and a variable indexed by its time domain. A constant
record broadcasts over the non-time dimensions at that first time point. A series
record supplies an initial profile with a shape matching only the non-time axes,
in their declared order. For dimensions `[cells, time]`, an initial series `[1, 3]`
supplies two cells at the initial time; it is not a full time trajectory.

Both lists are validated together before any values are fixed. Duplicate record
IDs, different records targeting the same variable, existing fixations, incompatible
units, shape errors and bound violations are rejected atomically. Initial conditions
may also be applied before discretization when the initial profile grid is final;
new time points remain free. Apply whole-time series after finalizing the time grid.

The builder never fixes values and no longer accepts `initial_values`. The old
`InitialValue` / `apply_initial_values` format and its optional `at` selectors are
removed. Information records require an explicit unit. Use an array-valued record
for a full initial profile rather than separate sparse cell selectors.

The application API does not require every default initial output to be fixed.
An alternative set, such as initial level and temperature instead of level and
energy, can determine the starting state through the physical equations. Checking
independence and solving for consistent initial conditions remain the caller's
responsibility. Solver initial guesses remain separate, free-variable values.
Steady models reject the `initial_values` list; use ordinary `specifications` for
steady operating conditions.

For differentiation, backward differences leave the first rate outside the
discretization equations. Its supplied initial value closes that endpoint; other
equations at the initial time can still restrict it. Different discretization
schemes have different endpoint coverage. This first example uses backward
differences and does not promise arbitrary differentiation models are suitable
for PETSc forward integration.

### Mixed liquid tank example

The generic `tank` model takes a `FluidProperties` argument and selects `mixed`
in both modes. `tank_flowsheet` supplies the concrete affine-water package.
The tank uses PH stream ports, prescribed vessel pressure, area, a withdrawal
flow and heat loss. Density and temperature come from the contents state block.
Mass and internal energy are the differentiated inventories:

```
mass_rate = inlet_flow - outlet_flow
energy_rate = inlet_flow * inlet_enthalpy - outlet_flow * outlet_enthalpy - heat_loss
mass = density(P, h) * area * level
energy = mass * enthalpy - pressure * area * level
```

Level is calculated from mass and current density, so thermal expansion does not
create mass. Initial level/temperature can replace initial mass/energy through
these algebraic relations. Pressure is prescribed; gas-space work, pressure
dynamics, kinetic/potential energy, flow reversal and empty-tank events are not
modelled. The example remains liquid-only.

Run from the repository root:

```bash
.venv/bin/python examples/dynamic_tank/run.py
.venv/bin/python examples/dynamic_tank/run.py --backend petsc
```

The example builds the same JSON in steady and dynamic modes. It applies Pyomo
backward-difference discretization, specifies inputs at all resulting points,
then solves with IPOPT or the IDAES PETSc wrapper. PETSc uses two endpoint
snapshots and adaptive integration internally; IPOPT uses 100 backward-difference
elements. Both require IPOPT for this example; the second also requires the
IDAES PETSc executable. The physical equations and initial-state calculations
remain in the JSON model. Python supplies numerical settings and specifications.
The example stores evidence in `examples/dynamic_tank/information.json` and
selects operating values and initial conditions in `specification.json`.
`steady_specification.json` selects the steady operating conditions. The script
applies specifications after discretization and sets solver guesses separately.

A relationship's `models` maps local aliases to definitions:

```json
"models": {
  "evaporator": {"model": "heat_exchanger", "domain_bindings": {"time": "time"}},
  "condenser": {"model": "heat_exchanger", "domain_bindings": {"time": "time"}}
}
```

Connections compile directly into Pyomo equality constraints. No Pyomo `Arc`
objects or arc-expansion transformations are used. They are shorthand for owned
constraints, not additional variable owners or a distinct required port object:

```json
"connections": {
  "transfer": {"from": "evaporator.hot_outlet", "to": "condenser.hot_inlet"}
}
```

Child inputs and outputs may both be connection sources: their public variables
are readable by the containing relationship. A parent input or output may also be a source.
Destinations remain child inputs or parent outputs; connections determine only
the destination variables. Reading a child input does not supply that input, so it
still requires specification unless another equation or connection supplies it.
A source may feed several destinations, but each destination is determined once.
Connections to the same struct at both endpoints are rejected. Both structs must
have exactly the same field names with dimensionally compatible units. Connections
convert units as needed. General equations require authors to use consistent units; construction
checks dimensional consistency. Connecting structs does not fix either endpoint.

## Generic model parameters

A model can declare named dependencies on other model definitions. These select
**definitions**, while implementation documents still select **relationships**.
For example, a generic state block declares:

```json
"model_parameters": {
  "FluidProperties": {
    "requires": {
      "state": {
        "direction": "input",
        "variables": {
          "pressure": {"unit": "Pa", "dimensions": ["time"]},
          "enthalpy": {"unit": "J/kg", "dimensions": ["time"]}
        }
      },
      "properties": {
        "direction": "output",
        "variables": {"temperature": {"unit": "K", "dimensions": ["time"]}}
      }
    }
  }
}
```

Relationships use that dependency through named model references:

```json
"models": {
  "fluid": {"model_parameter": "FluidProperties", "domain_bindings": {"time": "time"}}
}
```

A containing relationship supplies all arguments at its concrete reference:

```json
"models": {
  "states": {
    "model": "state_block",
    "domain_bindings": {"time": "time"},
    "model_arguments": {
      "FluidProperties": {"model": "water_property_package"}
    }
  }
}
```

A generic containing model can forward its own argument instead:

```json
"model_arguments": {
  "FluidProperties": {"model_parameter": "SourceFluid"}
}
```

Every reference must specify exactly one of `model` or `model_parameter`.
Arguments must exactly match the target's declarations; missing or extra arguments
and unknown parameter names are errors. A forwarded parameter already carries its
resolved arguments and cannot be given replacement `model_arguments`. Concrete
arguments may themselves name generic models with explicit nested arguments.
Parameter names are local to the declaring model; they are not inherited implicitly.

`requires` is a minimum structural interface. Supplied definitions may contain
extra structs or variables, but required fields must exist with matching directions,
value types and dimensions, and compatible units. This checks interface structure,
not physical meaning or numerical validity. If an interface does not constrain
something, the selected concrete model still determines its actual structure.
Normal connection checks still require matching complete field sets.

Resolved arguments belong to each occurrence and never modify shared model
definitions. The same generic model can be used with different property models
in separate branches. Constraint namespaces, `determines` rules and struct ownership
remain unchanged. Implementations still explicitly select the resolved children's
relationships; a supplied child `model` ID must match its resolved argument.

Root generic models are deliberately unsupported. Use a concrete wrapper such as
`water_state_block` or `heat_pump_flowsheet` to supply model arguments on its
child reference, then build the wrapper normally:

```bash
.venv/bin/python -m multifidelity.model_language water_state_block \
  examples/model_language/water_state_block_evaluate.json
```

The bundled `state_block` exposes one input `state` (flow, pressure and enthalpy)
and one output `properties` (temperature, entropy, density, heat capacity, vapor
fraction, bubble temperature and dew temperature). Its `fluid` child uses the configured `FluidProperties` argument.
Flow makes the state compatible with stream connections; only pressure and
enthalpy enter the property calculation. `water_state_block` supplies the configured
`water_property_package`; `helmholtz_water_state_block` supplies `helmholtz_water_ph`.
Both concrete examples contain the generic block at `states`. Transport properties
such as viscosity remain available on supporting property packages and are not
required by this thermodynamic state-block interface.

For a flowsheet inlet, instantiate `state_block` with the desired property package
and connect the inlet stream to `<block>.state`. Temperature can then be specified
at `<block>.properties.temperature` and enthalpy determined by the solver.
The standalone SGHP unit uses this pattern for its equipment inlet ports. The old `property_pair`, `water_property_pair` and
`helmholtz_water_property_pair` IDs and their two-state interfaces have been removed;
external implementations must migrate to the new IDs and single `fluid` child.


For a flowsheet boundary, use `state_block` directly as a child: its `state` input
can supply downstream equipment inputs without a separate parent input struct or
feed wrapper. For example:

```json
"connections": {
  "makeup_feed": {"from": "makeup_state.state", "to": "warm_water_mixer.makeup"}
}
```

The SGHP system uses `makeup_state`, `phnix_source_state`, and `cooling_water_state`
with Helmholtz water. Specify flow and pressure at `<block>.state.*` and temperature
at `<block>.properties.temperature`. The supplied information and observation
records use these paths. The temporary `feed` wrapper has been removed; equipment
inlet interfaces remain unchanged.

## Implementations and construction

`implementation.py` defines the Pydantic `ImplementationDocument` root and recursive
`ImplementationSelection` type. Every node requires an explicit `relationship`;
`submodels` maps local child reference names to further selections. No node
contains a model ID: the caller supplies the root model ID to `build_model()` or
the requirement queries, and child model references determine the descendants.
Leaves omit `submodels`, which defaults to an empty map.

```python
from multifidelity.model_language.implementation import ImplementationDocument

implementation = ImplementationDocument.model_validate_json(implementation_json)
implementation.submodels["states"].submodels["fluid"].relationship
```

These types check document shape only. They do not resolve references, check that
all children of a selected relationship are present, choose relationships
implicitly, or specify numerical values. Instance types remain deferred. The
builder accepts an `ImplementationDocument`, a dictionary, or a JSON file path.

The internal `_traversal.py` helper handles document parsing, selected relationship
and child checks, and recursive occurrence traversal for both construction and
requirement queries. It calls the shared checks in `_validation.py`. The backend
creates variables on entry and equations after visiting children; requirement
queries collect metadata without creating numerical objects. No additional public
`Implementation` class is required.


An implementation document chooses relationships for a separately supplied model:

```json
{
  "relationship": "flowsheet",
  "submodels": {
    "heat_pump": {
      "relationship": "cycle",
      "submodels": {
        "compressor": {
          "relationship": "isentropic",
          "submodels": {
            "inlet_state": {
              "relationship": "constant_properties",
              "submodels": {
                "water": {
                  "relationship": "constant_properties"
                }
              }
            },
            "outlet_state": {
              "relationship": "constant_properties",
              "submodels": {
                "water": {
                  "relationship": "constant_properties"
                }
              }
            },
            "isentropic_state": {
              "relationship": "constant_properties",
              "submodels": {
                "water": {
                  "relationship": "constant_properties"
                }
              }
            }
          }
        },
        "condenser": {
          "relationship": "lumped"
        },
        "subcooler": {
          "relationship": "lumped"
        },
        "ihx": {
          "relationship": "lumped"
        },
        "expansion_valve": {
          "relationship": "isenthalpic"
        },
        "evaporator": {
          "relationship": "lumped"
        },
        "source_inlet_state": {
          "relationship": "constant_properties",
          "submodels": {
            "water": {
              "relationship": "constant_properties"
            }
          }
        },
        "source_outlet_state": {
          "relationship": "constant_properties",
          "submodels": {
            "water": {
              "relationship": "constant_properties"
            }
          }
        },
        "sink_inlet_state": {
          "relationship": "constant_properties",
          "submodels": {
            "water": {
              "relationship": "constant_properties"
            }
          }
        },
        "sink_outlet_state": {
          "relationship": "constant_properties",
          "submodels": {
            "water": {
              "relationship": "constant_properties"
            }
          }
        }
      }
    }
  }
}
```

Each `submodels` key names a reference in the selected relationship. Every reference
must have an explicit relationship choice, even if its definition offers only one.
Extra selections are rejected. Nested `model` IDs may be omitted because the
reference determines them; if supplied they must match. No implicit selection
occurs in the loader. Recursive references require a finite implementation tree.

From the repository root:

```bash
.venv/bin/python -m multifidelity.model_language heat_pump_flowsheet \
  examples/model_language/heat_pump_cycle.json
```

Or in Python:

```python
from multifidelity.model_language import Library, build_model

model = build_model(
    "heat_pump_flowsheet",
    "examples/model_language/heat_pump_cycle.json",
    library=Library(),  # Bundled definitions; or Library("my/models")
)
model.pprint()
```

The result is a `ConcreteModel` with `model.fs` as a steady IDAES flowsheet.
Its root definition is materialized at `model.fs.root`:

```python
root = model.fs.root.relationship.models.heat_pump
root.structs.source_inlet.flow[0]
root.relationship.models.compressor.structs.performance.work[0]
root.relationship.constraints
root.relationship.connections
```

This is a generic equation structure inside IDAES, not an automatic translation
into the existing custom `UnitModelBlockData` equipment classes or thermodynamic
state blocks. Configurable property dependencies, shared material data, and
process-specific adapters are future work.

## List required input specifications

Before assigning any values, inspect the inputs required by a **complete selected
implementation**, including its nested models:

```python
from multifidelity.model_language import required_inputs, print_required_inputs

required = required_inputs(
    "water_state_block",
    "examples/model_language/water_state_block_evaluate.json",
)
# Sorted dictionary: root-relative variable path -> typed Variable declaration.
required["states.state.pressure"].unit  # "Pa"

print_required_inputs(
    "water_state_block",
    "examples/model_language/water_state_block_evaluate.json",
)
```

The same listing is available from the command line:

```bash
.venv/bin/python -m multifidelity.model_language water_state_block \
  examples/model_language/water_state_block_evaluate.json --required-inputs
```

It prints entries such as `states.state.pressure [Pa]`, one variable per
line. Both methods accept a typed `ImplementationDocument`, a dictionary, or a JSON file
path, and an optional `library`. `print_required_inputs` accepts `file` for writing
to a stream. Paths use local model-reference aliases and omit the root model ID.

Every root input is required. At each selected relationship, its constraints'
`determines` declarations and each connection's destination fields supply child
inputs. Only the remaining child input variables are listed, recursively. A
constraint may supply one member of a struct while the other members remain
required. Repeated uses of the same definition have distinct paths. Inputs remain
required even if the selected equations do not use them.

The water state-block example requires three variables: flow,
pressure and enthalpy. The block supplies pressure and enthalpy to its property
package through internal equations; the configured package supplies its coefficients
internally, so none are listed. Selecting a different
relationship can change the list; unselected alternatives are not traversed.

The query checks the implementation's root/model identities, explicit relationship
choices and complete child selections. It shares target coverage, duplicate
determination and connection direction/field checks with the backend. It does
not compile expressions, check equation units, establish mathematical determinacy,
create solver objects, fix variables, or fill any values. It relies on declared
`determines` targets. Targets may be implicit and need not occur in their
equations; users are responsible for mathematical determination and controllability. An incomplete definition such as the aggregate milk scaffold raises
its missing-output error instead of returning a misleading requirements list.
Apply operating values separately using the [specification API](#specification-documents).

## Bundled models and provenance

`models/` contains reusable JSON definitions. Explicit construction selections
live in `examples/model_language/`; these are examples, not an instance framework.

| Model | Existing source and scope |
| --- | --- |
| `heat_exchanger`, `heat_exchanger_flowsheet` | Configurable hot/cold property states, energy balances and counter-current smoothed LMTD; concrete water example |
| `valve` | Isenthalpic pressure-drop equations |
| `pump`, `compressor` | Incompressible pump efficiency and isentropic compressor efficiency with generic property arguments |
| `pump_flowsheet`, `compressor_flowsheet` | Concrete water-package examples for the pressure changers |
| `thermal_conditioner` | Time-indexed stream heating balance |
| `water_state` | Pressure/temperature liquid state with affine enthalpy and constant density, heat capacity and viscosity |
| `water_state_ph` | Pressure/enthalpy affine liquid-water model with zero vapor fraction and IF97 saturation-temperature metadata |
| `water_property_package` | Configured PH liquid-water wrapper supplying its own illustrative coefficients |
| `state_block`, `water_state_block` | Generic stream state and property calculation and a concrete water specialization |
| `mixer`, `splitter` | Time-indexed mixing and prescribed split |
| `flash_separator`, `flash_flowsheet` | Generic one-inlet phase router with configurable properties, per-phase split fractions and energy-conserving outlet mixing |
| `translator` | Identity topology scaffold; no composition or basis conversion |
| `heat_pump_flowsheet` | Concrete wrapper supplying independent property-model arguments to `heat_pump` |
| `heat_pump` | Aggregate COP equations and the cycle topology from `unit_models/heat_pump/cycle.py`, including subcooler and IHX |
| `source_loop` | Valve/pump/evaporator/heater/tank recycle from an earlier SGHP source-loop reconstruction |
| `milk_evaporator` | Aggregate mass/energy balances and MVR topology from `unit_models/milk_evaporator/detailed.py` |

These definitions demonstrate construction, ownership, scope and topology. They
are **not numerical reproductions** of the existing cases. In particular, the milk
aggregate balances are unclosed, so selecting that relationship now fails validation
with four missing output determinations (`milk_outlet.flow`,
`milk_outlet.enthalpy`, `milk_outlet.pressure`, `water_outlet.pressure`).
No placeholder equations were added to conceal those missing closures.
Effectiveness is declared but not enforced, and
the detailed scaffold omits composition, phase carryover and property correlations.
The flash scaffold performs a prescribed split rather than phase separation.
Some composite inputs remain unused by these initial formulations. Closed loops
may contain redundant continuity constraints. Construction success and dimensional
consistency do not establish determinacy, physical validity or solvability.

## Heat-pump COP ownership

Both heat-pump relationships expose heating COP as `performance.cop`, an output.
The aggregate relationship references `prescribed_cop` as `cop_model`; its
`cop_model.parameters.cop` input supplies the aggregate calculation and the public
COP output. The cycle relationship instead determines COP through
`performance.cop * performance.electrical_power = performance.heating_duty`.
Electrical power is also a public output in both relationships. The aggregate
relationship obtains prescribed power from `power_model.parameters.electrical_power`;
the cycle calculates it from `compressor.performance.work`. Compressor pressure
rise and efficiency are specified in the cycle.
COP is undefined at zero electrical power; this construction-only language does
not enforce a nonzero operating specification.

With the configured water property arguments, the aggregate example requires 8
input families, including the nested COP input; the cycle example requires 17,
with no specified COP. Neither requires external coefficient specifications. Parent relationships see
the same public interface regardless of the selected heat-pump relationship.


## Water state property model

`water_state` is an ordinary reusable model, not a new special type. Its
`constant_properties` relationship determines enthalpy, density, heat capacity,
viscosity and entropy, plus liquid vapor fraction (zero) and IF97 saturation
temperatures:

- `state` (input): pressure in Pa and temperature in K.
- `parameters` (input): reference pressure, temperature and mass-specific enthalpy,
  reference entropy, thermal expansion, constant density, mass-specific heat
  capacity and dynamic viscosity.
- `properties` (output): mass-specific enthalpy and entropy, density,
  mass-specific heat capacity, and dynamic viscosity.

The enthalpy equation is
`h = h_ref + cp * (T - T_ref) + (P - P_ref) / rho`.
Entropy uses the same affine approximation as the Python `LinearWater` model:
`s = s_ref + cp / T_ref * (T - T_ref) - alpha / rho * (P - P_ref)`.
Density, heat capacity and viscosity equal their supplied coefficients. This is a simple
single-phase liquid approximation, not a steam/phase-equilibrium model or a
validated water correlation. Its enthalpy form follows the existing
`property_models/linear.py`, while density here remains constant and viscosity
is a supplied constant. No detailed-water alternative is declared until it has
actual property equations.

```bash
.venv/bin/python -m multifidelity.model_language water_state \
  examples/model_language/water_state_constant_properties.json
```

Like other model builds, this creates free variables with optional defaults and does not solve.
A caller must eventually specify both the state and the coefficients. For
example, an illustrative coefficient set is `T_ref = 298.15 K`,
`P_ref = 101325 Pa`, `h_ref = 104920.1198085 J/kg`, `cp = 4180 J/(kg K)`,
`rho = 997 kg/m³`, `mu = 0.00089 Pa s`, `s_ref = 367.1996421 J/(kg K)`,
and `alpha = 0.000257 / K`; these are not built-in defaults on raw state models.

An equipment relationship can reference separate `water_state` models for inlet
and outlet property calculations and determine their state inputs through
constraints or connections. These occurrences each own their variables. The generic
`state_block` example instead uses the configured PH `water_property_package`. The heat pump uses independently configurable pressure-enthalpy
property models, described below; other equipment definitions are not yet
parameterized.

## Heat-pump hot-side and cold-side properties

`heat_pump` declares `HotSideProperties` for the sink and `ColdSideProperties`
for the source, plus `RefrigerantProperties` (PH) for all compressor state
calculations. The cycle instantiates that same property model for its inlet,
outlet and isentropic reference. Both relationships create
separate inlet/outlet state blocks on each side. Whole-stream connections supply
flow, pressure and enthalpy from the corresponding public port. Calculated temperature stays
on each internal package's `properties.temperature`; it is not a public heat-pump
output. The heat pump has no property-coefficient input structs.

Each argument must accept pressure and enthalpy and supply the seven
thermodynamic fields required by `state_block`. No particular coefficient interface is required.
Additional fields are permitted; any unsupplied package-specific inputs remain
discoverable by `required_inputs()`.

`heat_pump_flowsheet` supplies `water_property_package` independently for the
source, sink and refrigerant PH arguments on its `heat_pump` reference.
No separate isentropic-property argument is required. Both examples select this concrete
flowsheet as the root; its heat-pump child selects either `aggregate` or `cycle`.
Root generic models remain unsupported. A parent chooses the property definitions
through `model_arguments`; the implementation selects their relationships.

`water_property_package` wraps the pressure-enthalpy model `water_state_ph`,
supplying its eight coefficients with dimensioned constant equations and forwarding
its state and property structs. It uses `T_ref = 298.15 K`, `P_ref = 101325 Pa`,
`h_ref = 104920.1198085 J/kg`, `cp = 4180 J/(kg K)`, `rho = 997 kg/m³`, and
`mu = 0.00089 Pa s`, `s_ref = 367.1996421 J/(kg K)`, and
`alpha = 0.000257 / K`. These are illustrative liquid-water coefficients owned by
this concrete package; the reusable `water_state_ph` itself still requires
explicit coefficients. Its temperature equation is
`T = T_ref + (h - h_ref - (P - P_ref) / rho) / cp`.
This is a single-phase liquid approximation, not a refrigerant or steam package.

The configured package requires only pressure and enthalpy:

```bash
.venv/bin/python -m multifidelity.model_language water_property_package \
  examples/model_language/water_property_package_constant_properties.json --required-inputs
```

Exchangers instantiate four state blocks with independently configurable
`HotSideProperties` and `ColdSideProperties`. Counter-current terminal differences
are `T_hot,in - T_cold,out` and `T_hot,out - T_cold,in`, and duty is conductance
multiplied by their logarithmic mean. `log_mean_temperature_difference` uses the
IDAES smoothed LMTD expression (epsilon 1e-10), including its equal-endpoint limit.
Terminal differences must be positive; temperature crosses and a fully pinched
zero-duty state are outside this formulation. No externally supplied temperature
difference remains. The generic heat pump forwards its refrigerant, sink-water
and source-water packages to the appropriate exchanger sides.

Simple water reports vapor fraction zero and real saturation temperatures using
[IAPWS-IF97 region 4, Eq. 31/Table 34](https://iapws.org/technical-guidance/release/IF97-Rev).
The pressure range is 611.213 Pa to 22.064 MPa. These metadata do not make the
affine liquid equations a two-phase package. Helmholtz packages additionally
provide phase and saturated enthalpies; those are required for the flash unit.

## Efficiency-based pressure changers

Both `pump` and `compressor` expose inlet/outlet mass flow, pressure and specific
enthalpy. They take `parameters.pressure_rise` and `parameters.efficiency`, and
calculate `performance.work` (positive work into the fluid). With the inlet
state specified, each concrete example needs five specifications per time point. No
power specification is required for these pressure-driven examples.

The pump's `incompressible` relationship follows IDAES's incompressible pump
assumption: `fluid_work = pressure_rise * outlet.flow / outlet_density`,
`efficiency * work = fluid_work`, and the adiabatic enthalpy-flow balance.
It takes a PH `FluidProperties` argument exposing density and reports fluid
work as `performance.fluid_work`.

The compressor's `isentropic` relationship uses a single PH `FluidProperties`
argument for separate inlet, actual outlet and hypothetical isentropic state
occurrences. The reference has the actual outlet pressure, while an equation
constrains its **calculated entropy** to equal the inlet entropy. Its enthalpy
remains a free PH state variable that the equation-oriented solver determines.
The entropy equality declares `isentropic_state.state.enthalpy` as its
`determines` target through the property model's dependency graph.

`isentropic_work = inlet.flow * (isentropic_state.state.enthalpy - inlet.enthalpy)`,
`efficiency * work = isentropic_work`, and the adiabatic energy balance determine
actual work and outlet enthalpy. `performance.isentropic_work` is also exposed.
All three occurrences share the chosen fluid definition and reference conventions,
but own distinct variables. The compressor has no `IsentropicProperties` argument.
The heat pump likewise forwards only `RefrigerantProperties` to its compressor.

The obsolete PS and isentropic-package alternatives have been removed. Ordinary
pump/compressor states use stream state blocks; the isentropic reference remains
a flowless PH calculation. The default affine-water examples are illustrative
and do not provide validated vapor-compressor physics.

`pump_flowsheet` and `compressor_flowsheet` supply the concrete package arguments:

```bash
.venv/bin/python -m multifidelity.model_language pump_flowsheet \
  examples/model_language/pump_flowsheet.json --required-inputs
.venv/bin/python -m multifidelity.model_language compressor_flowsheet \
  examples/model_language/compressor_flowsheet.json --required-inputs
```

The detailed milk example retains specified MVR power and efficiency, with its
power equation determining the MVR compressor's pressure-rise input through the
child work calculation. This uses the descendant-dependency validation described
above. It does not establish numerical solvability of the full milk scaffold.

## Information model

Record available evidence separately from the model definitions and from decisions
about how to specify or estimate a particular instance. `information.py` implements
record validation, loading, insertion and trust-ordered candidate lookup. Applying
records to model instances is supported by specification documents; the
initial trust-ranked DM specification selector is implemented; further selection
research remains proposed.

Information is a **list of records**, not a dictionary keyed by variable path.
Multiple records may target the same variable: for example, a sensor reading,
control setpoint and assumption may all refer to the same temperature. Preserve
those records independently rather than overwriting one with another.

Each record has:

| Field | Meaning |
| --- | --- |
| `id` | Unique identity of the information record |
| `tag` | Tag name for linking to external systems; distinct from the record identity |
| `information_type` | One of `sensor_reading`, `control_setpoint`, `equipment_specification`, `parameter`, or `assumption` |
| `variable_path` | Path to the variable family, without individual index subscripts |
| `type` | `constant` (default) or `series` |
| `value` | One number for a constant, or a rectangular numeric array for a series |
| `unit` | Unit in which the value and its standard deviation are expressed |
| `standard_deviation` | Optional nonnegative uncertainty in the same unit as `value` |
| `trust_rank` | Integer from 1 to 10; higher ranks are prioritized when selecting specifications |

For now, use variable paths directly. Assume shared public variables retain their
paths and physical meanings across fidelity choices; do not introduce a separate
physical-quantity identity/mapping system at this stage. Paths to relationship-
specific internal variables still need to exist in the selected implementation.

Standard deviation is the only uncertainty representation for now. Omitted means
unknown uncertainty; zero explicitly means the value is treated as exact. Do not
interpret omitted uncertainty as zero or introduce percentage/bound variants.
One standard deviation applies to every entry of a series; per-entry uncertainty
and correlation models are not introduced.

```json
[
  {
    "id": "sink_temperature_observation",
    "tag": "TT101",
    "information_type": "sensor_reading",
    "variable_path": "sink_inlet.temperature",
    "type": "series",
    "value": [323.15, 324.15, 325.15],
    "unit": "K",
    "standard_deviation": 0.2,
    "trust_rank": 10
  },
  {
    "id": "sink_temperature_target",
    "tag": "TSP101",
    "information_type": "control_setpoint",
    "variable_path": "sink_inlet.temperature",
    "type": "constant",
    "value": 324.15,
    "unit": "K",
    "trust_rank": 5
  }
]
```

Information type describes the source or nature of a record; it does not yet
choose its mathematical role. A record does not automatically fix a model variable,
and a control setpoint does not automatically establish the actual achieved value.
The proposed baseline selects records by descending `trust_rank`: for example,
10 may describe highly trusted actual plant data and 1 a rough estimate. Rank is
an assigned ordinal priority, separate from information type and standard deviation;
it is not a probability or inverse variance. Do not compare raw standard deviations
across different quantities to establish trust. Equal ranks initially use record
ID as a deterministic tie-break.

Records for one variable family are alternatives, each describing a complete
constant or series. Normally use the highest-ranked
applicable record; retain lower-ranked records as fallbacks when the preferred
record cannot be used. They do not supply additional independent specifications
and are not averaged or fixed simultaneously. For the initial algorithm, selected
central values are fixed as an approximation, even for noisy records, with their
uncertainty retained in the audit trail. Fallback estimates used to close the
model are fixed assumptions, distinct from solver initial guesses.

See the [trust-ranked DM specification algorithm and separate experiment outlines](../../../research-ideas/information-directed-specification.md)
for structural candidate selection, auditable specification documents, and future
noise/conditioning studies. The initial structural loop is implemented by `select_specification()`; see
the automatic structural specification selection section below.
Series use the numerical grid's index order. They do not carry separate timestamps,
per-point selectors, or interpolation rules. Apply them after finalizing the grid
through the separate specification API.

### Constant and series values

A `constant` has one numeric value, which can be broadcast over all indices or
used for a scalar parameter. Omitting `type` preserves existing scalar records as
constants. A `series` contains a value for every index, as a JSON list or nested
list. Python callers may also pass tuples or NumPy arrays. All entries must be
finite real numbers; empty, ragged, boolean, and nonnumeric arrays are rejected.
Explicit `type="series"` is required for arrays.

Array axes follow the variable's declared dimensions. For a time-only variable,
`value` is a one-dimensional list with one entry per time. For dimensions
`["time", "cells"]`, it has shape `(number_of_times, number_of_cells)`.
Series length and shape must match the **final grid after discretization**.
There is no automatic resampling, interpolation, or snapping to grid points.

Record values are stored as immutable nested tuples so changing a supplied list
or ndarray cannot change table contents. `model_dump_json()` and
`model_dump(mode="json")` serialize them as ordinary JSON arrays.

```python
series = InformationRecord(
    id="inlet_temperature_series", tag="TT101",
    information_type="sensor_reading", variable_path="inlet.temperature",
    type="series", value=[303.15, 305.15, 310.15],
    unit="K", standard_deviation=0.2, trust_rank=10,
)
series.shape  # (3,)
series.validate_shape((3,))
# series.validate_shape((2,)) raises ValueError

# After constructing/discretizing a model with time points [0, 30, 60]:
values = series.values_for(model.fs.root.structs.inlet.temperature)
# {0: 303.15, 30: 305.15, 60: 310.15}
```

`validate_shape(shape)` checks series shape; constants can broadcast to any valid
shape. `values_for(variable)` performs that check against the variable's current
grid and returns an index-to-value dictionary. A scalar target uses key `None`.
Series mapping requires ordered, one-dimensional index domains, as used by this
model language, and follows their iteration order. Constants do not require an
ordering and broadcast across every index.

These helpers do not resolve `variable_path`, convert units, select a record, set
values, or fix variables. The returned numbers remain in the record's declared
unit. They expose the mapping for a later specification/observation step while
keeping information separate from decisions about its use.

Run `.venv/bin/python examples/information/show_records.py` to load constant and series
alternatives from `examples/information/records.json` and map them onto a
discretized tank inlet without changing any model values.

### Information-table interface

`InformationDocument` is a Pydantic `RootModel` whose root is a tuple of
`InformationRecord` objects. Its JSON representation remains an array. Like model,
implementation and specification documents, it supports `model_validate()`,
`model_validate_json()`, `model_dump_json()`, `from_json()` and `load_json()`.


```python
from multifidelity.model_language import InformationRecord, InformationDocument

# JSON files contain an array of records, as above.
table = InformationDocument.load_json("information.json")
# Or parse JSON text directly: InformationDocument.from_json(json_text).

table.add(InformationRecord(
    id="sink_temperature_assumption",
    tag="sink_temperature_fallback",
    information_type="assumption",
    variable_path="sink_inlet.temperature",
    value=323.15,
    unit="K",
    trust_rank=1,
))

record = table.get("sink_temperature_assumption")
alternatives = table.candidates("sink_inlet.temperature")
```

`add` accepts either an `InformationRecord` or a dictionary and returns the
validated record. The table can also be constructed from an iterable of records
or dictionaries. Invalid records and duplicate IDs are rejected without replacing
an existing record. Repeated tags and variable paths are allowed.

`records` returns the records in insertion order. `candidates` returns all records
for an exact variable path, sorted by descending trust rank and then record ID;
no match returns an empty list. `get` raises `KeyError` for an unknown record ID.
The returned lists do not expose the table's mutable storage, and records are
immutable so their IDs and validated fields cannot change after insertion.

Values and standard deviations must be finite, standard deviations nonnegative,
and trust ranks integers from 1 through 10. Missing standard deviation remains
`None`. Loading checks record shape, not existence of variable paths in a selected
model, physical applicability or unit compatibility. The table describes one
operating case and neither selects a winning record nor fixes any model variables.

## Numerical variable lookup

Use `get_variable(model, variable_path)` to access a live variable family using
the same root-relative paths as information records:

```python
from multifidelity.model_language import get_variable

pressure = get_variable(model, "inlet.pressure")
pressure_at_start = pressure[model.fs.time.first()]
# Nested occurrence example: get_variable(model, "heat_pump.compressor.inlet.pressure")
```

Scalar families return scalar Pyomo variables; indexed families are indexed by the
caller. The lookup follows cloning and discretization. Unknown paths and models
not built by `build_model()` raise `ValueError`.

## Specification documents

A `SpecificationDocument` selects information-record IDs and records which
canonical input each noncanonical operating fixation replaces:

```json
{
  "specifications": ["inlet_pressure", "measured_temperature"],
  "replacements": {"measured_temperature": "state.enthalpy"},
  "initial_values": []
}
```

The information document supplies paths, values, units, trust and uncertainty.
In this example, `inlet_pressure` targets `state.pressure` directly, while
`measured_temperature` targets `properties.temperature`. Fix temperature and leave
`state.enthalpy` free. The model and its selected implementation supply the
equations and canonical inputs; none are embedded in this document.

A **canonical input** is a public input not supplied by a selected parent
constraint, connection or derivative. `canonical_inputs(model)` returns these
families by root-relative path. Every ordinary fixation must either target one
of them directly or have an explicit `replacements` entry naming one. Each
canonical slot can be used once, and each target can be fixed once. Replacement
keys must be selected operating record IDs; values are canonical variable paths,
not other record IDs. Paired families must use the same index domains and grid.
Physical equations, connection directions and `determines` remain unchanged.

All three fields default to empty. Old direct-input documents remain valid;
output or supplied-input fixations need pairs. Generate them without changing
the chosen records using:

```python
from pathlib import Path
from multifidelity.model_language import pair_specification, specification_slots

specification = pair_specification(model, specification, information)
# Save or edit specification.replacements before application.
Path("paired_specification.json").write_text(specification.model_dump_json(indent=2))
```

`pair_specification()` uses structural maximum matching (the basis of DM),
then prefers the same model occurrence, shorter hierarchy distance, shorter
incidence-graph distance and finally canonical path. It reserves direct inputs
and honours explicit user pairs before inferring others. Recompute from the full
chosen record set to let later direct fixations reassign earlier automatic pairs.
No equipment, variable-name, physical-quantity or unit-based pairing rules exist.
The optional upstream heuristic remains future work. The helper does not fix or
solve, and canonical reference fixations are virtual graph operations needing no
numerical values. A complete reference stays complete; an already deficient
reference may improve but must not worsen under an exchange.

`initial_values` retains its separate dynamic first-time-slice meaning and is not
interpreted as a whole-family replacement. Operating replacements work on steady
or finalized dynamic grids; automatic initial-condition pairing is deferred.
Duplicate record IDs and different records targeting the same family, including
across the two lists, are rejected. Paths name families without index selectors.

```python
from multifidelity.model_language import (
    InformationDocument, SpecificationDocument,
    apply_specification,
)

information = InformationDocument.load_json("information.json")
specification = SpecificationDocument.load_json("specification.json")
# model is the object returned by build_model(...).
apply_specification(model, specification, information)
```

The method also accepts a specification dictionary or JSON file path.
`SpecificationDocument.from_json(text)` parses JSON text, and
`model_dump_json()` serializes the document. The information argument must be an
`InformationDocument`. Numerical models must come from `build_model()`.

Application validates all paths, record references, duplicate targets, array shapes,
unit conversions, finite converted values, variable bounds, existing fixations,
slot ownership, connectivity and structural exchange admissibility before fixing
any variable. It updates the model in place and returns `None`. A validation error leaves all values and fixation statuses
unchanged. Existing fixations are rejected, even if equal; applying a new document
does not silently replace an earlier specification or an initial condition.

For ordinary specifications, constants broadcast over the current grid and series
must match the full ordered domain product. Initial values instead use the first
time slice and series match the non-time dimensions. Scalar variables support
ordinary specifications but cannot have initial values. Finalize grids before
application; there is no automatic interpolation or reapplication after discretization.

Selected central values are fixed even for uncertain records. The source records,
including uncertainty and trust rank, remain unchanged. The API does not rank
information, determine whether a control setpoint is achieved, protect prediction
targets, assess structural completeness or solve the model. Partial documents
are allowed; selection policy belongs to the caller or `select_specification()`.
Structural diagnostics and solver results remain separate from the document.

`specification_slots(model)` reports applied canonical paths, fixed target paths
and record IDs. `audit_fixations(model)` rejects unexplained public noncanonical
fixes, refixed replaced inputs and missing managed target fixations. Selection and
hierarchical initialisation call this audit at entry. Native implementation
configuration and first-slice initial conditions have separate scopes. For direct
calls to an external Pyomo solver, call the audit explicitly if raw `.fix()` calls
might have bypassed specification application. To change a saved pair, edit the
document and apply it to a freshly built model; application never silently undoes
an already applied specification.

The [complete valve example](../../../examples/specification/README.md) loads all
three documents, fully specifies the model and solves it with IPOPT.

## Proposed quantity-of-interest specification

Identify what we want to predict with a list of target variable paths:

```json
{
  "quantities": [
    { "variable_path": "performance.electrical_power" },
    { "variable_path": "sink_outlet.temperature" }
  ]
}
```

Each entry contains only `variable_path`, using the same model-variable path
convention as information records. Prefer shared public variables so the targets
retain their meaning across fidelity choices. Paths must exist in the model used
for the analysis; the example does not imply every model exposes both quantities.

Omit tolerances, accuracy requirements and uncertainty thresholds for now. The
specification does not select an implementation, fix target values, reference a
model, or contain references to information records. Combining it with the model
and information table defines the analysis task; no separate analysis-task data
structure is introduced here. This section records the agreed shape only, not an
implemented selection or prediction algorithm.

## Future idea: measurement-directed fidelity selection

A possible future query is: **which relationship (fidelity) choices can influence
this measured output?** This would derive dependencies through equations,
connections and nested model references, rather than merely list definition fields.
It could help a selection algorithm focus refinement on parts of the model that
affect measured quantities.

This is an exploration idea, not an implemented feature. Structural dependencies
may be obtainable from the definition expressions and `determines` declarations;
numerical sensitivity and the magnitude of a fidelity's effect would require
additional analysis, potentially using the Pyomo backend. Cycles, implicit coupled
equations and changing internal topology would need careful treatment. A dependency
path alone does not establish a nonzero effect or quantify its importance.

## Future integration questions outside the core algorithm

The following areas will need investigation, but are not central to the current
algorithm for choosing fidelities and specifying models from available information
and quantities of interest. They are open questions, not implementation commitments
or prerequisites for the initial bounded experiments.

- **1D unit operations:** How should JSON represent spatial domains, indexed
  variables, distributed equations, boundary conditions and discretization?
- **Dynamic state transfer:** Steady/dynamic rebuilding and initial specifications
  are supported. Automatic transfer between representations and fidelity-dependent
  initial profiles remain open.
- **External Pyomo and machine-learning models:** Scalar symbolic providers can
  be repeated over time through external relationships; see the
  [how-to guide](custom-models.md). Native spatially indexed provider interfaces
  remain future work. Optional model-specific initialisation callbacks are supported.
- **Parameter estimation:** How does estimation interact with our implementation
  selection and instance-specification methods, including information records,
  uncertainty and quantities of interest? What should be fixed, estimated or
  treated as an observation for a selected representation?

## Deferred decisions

- Continuous spatial domains and derivatives; automatic backend discretization
  configuration (time dynamics can use Pyomo's existing transformations).
- General fixed/free instance documents and automatic starting-value propagation.
- Numerical recovery and extensions beyond the initial DM specification selector.
- Detailed thermodynamics, component mixtures, shared material data, configurable
  equipment property dependencies, validated detailed equations and calibration.
- JSON Schema authoring support, definition version pinning and broader diagnostics.
- Aggregate-first initialisation, numerical recovery and fidelity switching in place.

The builder checks selected references, scope, names, directions, connection fields,
equation units, explicit determination targets, duplicate determinations and missing
outputs. It is not yet a comprehensive document-schema validator.

## Heat-pump milk-evaporator flowsheet

`heat_pump_evaporator_flowsheet` combines `steam_generating_heat_pump_system`,
a direct-steam-injection `mixer`, and three serial `milk_evaporator` occurrences.
The system's public steam outlet supplies injection without reaching through its
internal models. Its boundary water states are specified inside the system;
the composite root has only the milk inlet. Each effect exports a water outlet
and the last effect supplies the milk product. There is no condensate return.

The example selects a cycle SGHP, aggregate PHNIX, injection `balance`, and
`detailed` milk effects. The SGHP/PHNIX choices remain independent. Milk composition,
condensation during injection and calibrated milk-evaporator behavior remain
outside this illustrative example; its current property arguments are water
approximations. The old standalone SGHP scaffold and its aggregate example have
been removed.

```bash
.venv/bin/python -m multifidelity.model_language heat_pump_evaporator_flowsheet \
  examples/model_language/heat_pump_evaporator_flowsheet.json --required-inputs
```

## Automatic structural specification selection

`select_specification(model, information, prediction_targets=(),
excluded_record_ids=(), achieved_setpoint_ids=())` implements the initial
trust-ranked DM loop for a fixed implementation and finalized numerical grid.
It works on a clone and leaves the supplied model unchanged.

```python
from multifidelity.model_language import select_specification, apply_specification

selection = select_specification(model, information,
                                 prediction_targets=["outlet.pressure"])
if selection.complete:
    apply_specification(model, selection.specification, information)
```

The selector considers active equality constraints and every free variable,
including isolated variables. Records are tried in descending trust rank, with
record ID breaking ties. It recomputes DM after each trial and accepts a
whole-family fixation only if it reduces unmatched unknowns without creating
an overconstrained region. Existing fixations are mandatory context. Invalid
records are skipped with reasons, allowing lower-ranked alternatives to be tried.
Control setpoints require explicit inclusion in `achieved_setpoint_ids`; callers
must filter other operating-context applicability using `excluded_record_ids`
or a filtered information document. Prediction target paths are reserved.

The result contains the specification document, `complete`, initial and remaining
deficiency, unresolved variable names, overconstrained constraint names, and
per-record decisions including values, units, uncertainty and deficiency changes.
An initially overconstrained model returns incomplete diagnostics without adding
fixations. A partial document is returned when evidence is insufficient.

After choosing records, the selector automatically generates replacement pairs
without changing the selected information set. `decisions` includes `replaces`
for chosen records; `pairing_error` is `None` when pairing succeeds. If a selected
set cannot be paired, `complete` is false and `pairing_error` explains why. Do not
apply an unresolved document. A successfully paired partial document may still
be applied while its remaining structural deficiency is reported separately.

This is structural selection, not a numerical solvability or uniqueness check.
It does not solve, reconcile noisy data, inspect inequalities, select dynamic
initial conditions, or change fidelity. See the valve specification example.


## Steam-generating heat-pump demonstration system

`steam_generating_heat_pump_system` describes the main process paths of the
Waikato SGHP plant: source-water, warm-water, and hot-water loops, a PHNIX source
heat pump, cooling exchanger, flash tank, makeup, and steam export. Its `sghp`
and `phnix` children independently select aggregate COP or component-cycle
relationships without changing the plant connections.

`steam_generating_heat_pump_unit` exposes source, hot and warm water circuits.
It replaces the earlier SGHP scaffold. The generic `flash_separator` binds
Helmholtz water in this system and routes each inlet phase between two outlets,
without prescribed phase enthalpies. Inlet state blocks support temperature-based
specifications. The SGHP and PHNIX cycles use butane and propane Helmholtz
properties respectively, including their exchanger states.

See [the demonstration guide](../../../examples/steam_generating_heat_pump_system/README.md)
for four implementation documents, construction commands, P&ID provenance,
information paths, copied Ahuora configuration with provenance, and limitations.
All four plant representations construct; the aggregate SGHP unit also has an
IPOPT replay calibrated at the captured point. The full closed plant still needs
a consistent operating specification and numerical validation.

### Pipe relationships

`pipe` has `pass_through` and `lumped` relationships, selected by
`examples/model_language/pipe_pass_through.json` and `pipe_lumped.json`.
Both expose time-indexed inlet/outlet flow, pressure and specific enthalpy.
Pass-through equates all three and requires no geometry or initial inventory.

The generic pipe takes a `FluidProperties` argument; `pipe_flowsheet` provides
an affine-water example. The lumped relationship selects `contents`
(`pipe_holdup`), with scalar length and diameter. Its fixed cylindrical volume is
`pi * diameter**2 * length / 4`, and density comes from the contents state block.
The balances are:

```
m = density(P, h) * volume
U = m * h - P * volume
dU/dt = inlet_flow * inlet_enthalpy - outlet_flow * outlet_enthalpy
dm/dt = inlet_flow - outlet_flow
```

Pressure follows the inlet without momentum dynamics. Outlet flow can differ
from inlet flow while density changes; prescribing both equal would lose mass
conservation during thermal expansion. With the affine constant-density example
they are equal, recovering a mixed thermal lag. This is not a spatial transport
delay. Wall storage and heat loss are omitted.

The dynamic selection requires an initial energy (or a consistent alternative
such as contents enthalpy). Contents mass is constrained by density and fixed
volume. The derivative-output discovery convention also lists `rates.mass` at
the initial point: the constant-density example specifies zero initial mass
rate. Variable-density initial conditions must be consistent with the chosen
thermal and pressure evolution. Paths under the
concrete example begin `pipe.contents.*`. Steady accumulation is zero; with
nonzero flow the outlet enthalpy equals the inlet. A zero-flow steady inventory
needs an additional thermal specification.

### Diagnosing conflicting specifications

`relax_specifications` constructs an independent optimization model from an
already specified model. It replaces each selected information-table fixation
with a signed, dimensionless slack and minimizes
`sum(weight * (scale * (value - target))**2)`. Scales multiply values in the
variable's native units; an absent scale is 1. Optional positive weights are
keyed by information-record id. Larger weights resist movement more strongly.

```python
from multifidelity.model_language import relax_specifications

relaxed = relax_specifications(model, specification, information,
                               weights={"measured_flow": 10})
result = solver.solve(relaxed.model)
changes = relaxed.deviations()
```

The original model and information records are unchanged. On the diagnostic
clone, other fixed variables, bounds and physical equations remain hard; existing
objectives are deactivated. The report includes target, adjusted value, signed
physical deviation, scale, normalized deviation and weighted penalty. Entries
are ranked by penalty. Check solver termination and physical equation residuals
before interpreting the ranking. It describes joint changes under the chosen
weights, rather than identifying a uniquely incorrect measurement. All selected
records are softened, including assumptions and equipment parameters; select a
subset if some specifications must remain hard.

### Defining circulation in a mass recycle

Definition coverage does not guarantee global equation independence. For a
closed loop of components that conserve flow, the final continuity equation can
repeat the others even though every equation has a distinct `determines` target.

The bundled `mass_recycle_definition` model provides a definition point with
standard inlet/outlet stream structs and an additional `flow_definition.flow`
input. Pressure and enthalpy pass through; outlet flow comes from that separate
input, while the standard inlet flow is unused internally. The rest of the loop
still enforces continuity. This keeps ordinary connections and output-definition
validation without requiring a solver to remove dependent equations. The SGHP
plant uses it between the PHNIX sink outlet and SGHP source inlet, leaving the
separate flow input free so the loop energy balances determine circulation.

### Exporting numerical results

`export_results` takes a snapshot of all declared public variables, including
nested model occurrences, after values have been loaded into a built model:

```python
from multifidelity.model_language import export_results, ResultsDocument

snapshot = export_results(
    model, status="optimal", solver="ipopt", termination_condition="optimal",
    specification=specification,
)
snapshot.write_json("results.json")
loaded = ResultsDocument.load_json("results.json")
```

Export does not solve, change values/fixity, infer convergence or validate
physical applicability. Status is explicit and defaults to `not_solved`.
Use `failed` for an unsuccessful attempt; retained values may then be guesses or
partial initialization states. Internal native-provider variables are excluded.

The version 1 document includes a run ID, timezone-aware creation timestamp,
root model ID, full implementation choice tree, steady/dynamic mode, time unit,
solve metadata, optional specification IDs, and variable families keyed by
root-relative occurrence path. Each family records its numerical unit, declared
dimension order, and entries with explicit index coordinates, value and fixed/free
state. Scalars use an empty coordinate list; discretized variables include the
actual post-discretization grid. Unset and nonfinite values use JSON `null` with
an explicit `issue` marker. Units are not converted for display. The document is
separate from information records, which describe observations and assumptions.

Upload this file in the model viewer's **Results** tab to inspect values and,
when implementations match, show saved values on diagram rows. The SGHP
`attempt_bottom_up.py` example now writes `results.json` alongside its diagnostic
report. Model identity and implementation are recorded, but the document does
not embed or fingerprint the library's equation definitions.

### Portable viewer workspaces

A `WorkspaceDocument` bundles exactly three fields: `implementation`, `information`
(the information-record array), and `results` (a complete `ResultsDocument`). It
contains no separate root-model field, model definitions, layouts, rotations,
flips, current view or navigation state. The existing `results.model_id` identifies
the model when opening it in the viewer; that definition must be in the library.
The implementation must match the implementation already captured in the snapshot.

```python
from multifidelity.model_language import export_workspace, WorkspaceDocument

# After solving, using the actual information including case-specific overrides:
export_workspace(
    model, information,
    status="optimal", solver="ipopt", specification=specification,
).write_json("workspace.json")

# Or package an existing snapshot without changing its run ID, timestamp or status:
WorkspaceDocument.from_results("results.json", "information.json").write_json("workspace.json")
```

Export never solves or infers convergence. Explicit status has the same meaning as
`export_results`; defaults remain `not_solved`. Failed/unset values retain their
snapshot diagnostics. `WorkspaceDocument.load_json()` reads the same portable file.
Loading a workspace in the viewer replaces the three documents for its model and
uses the existing local-storage behavior. It leaves diagram layout/orientation
preferences untouched.
