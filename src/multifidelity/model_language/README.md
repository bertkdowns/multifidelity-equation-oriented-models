# JSON model specification language

This is a first construction-only implementation of the model language discussed
for recursive multifidelity modelling. It builds a selected equation hierarchy
inside an **IDAES** `FlowsheetBlock`, using Pyomo blocks, variables and constraints.
It does not solve, set initial guesses, or construct full instance documents.
An optional `initial_values` argument fixes explicitly supplied initial entries;
ordinary operating inputs remain free until specified by the caller.
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

The existing Python models combine physical equations, IDAES property packages,
formulation builders and case-specific setup. This folder explores expressing the
reusable mathematical definitions as data, so a model's public interface can stay
stable while alternative internal formulations are selected recursively.

JSON is the source of truth: one file per reusable model, readable and reviewable
in Git. Model IDs are independent of filenames. No database is required. A future
editor or SQLite index can operate on the same conceptual definitions.

This is separate from the working Python models; it does not replace them. Their
current ownership conventions and fidelity activation behaviour remain as
specified in `docs/design.md`. The new language uses the vocabulary and ownership
below, including separate boundary variables joined by equations in composites.

## Vocabulary and ownership

| Concept | Meaning and owner |
| --- | --- |
| Variable | Scalar mathematical quantity owned by exactly one struct |
| Struct | Named collection of variables, owned by a model; entirely input or output |
| Constraint | Equation, owned by a relationship; references existing variables |
| Model | Reusable definition owning structs and alternative relationships |
| Model reference | Named use of a reusable definition, owned by a relationship |
| Relationship | Alternative formulation owning model references and constraints |
| Implementation | One relationship selection per model occurrence, recursively |
| Instance | An implementation plus variable specifications; deferred |

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
from multifidelity.model_language.definitions import Model

model = Model.model_validate_json(Path("my_model.json").read_text())
model.structs["inlet"].variables["pressure"].unit
model.relationships["basic"].models
```

`Library` loads every JSON document into these types. Both `library.models["valve"]`
and `library.get("valve")` return a `Model`, and the builder consumes its typed
structs, relationships and reference variants directly. Definition documents retain model IDs and generic references for serialization.
Resolved navigation is supplied separately by `resolution.py`; it does not unroll
a tree or select implementations.

Document-shape validation rejects unknown fields, invalid component names,
missing required fields, unsupported variable types, invalid directions and
ambiguous reference kinds at load time, including in unselected alternatives.
Scope, generic interface compatibility, dimensions supported by the backend,
equation units and determination checks remain in the builder and apply to the
selected implementation. Implementation selections remain dictionaries for now.
Serialize definitions with `model_dump(by_alias=True)` or
`model_dump_json(by_alias=True)` to preserve JSON names (`Connection.from_` in
Python is `from` in JSON). Instance types remain deferred; implementation types are described below.

## Resolved definition navigation

`resolution.py` owns library loading, model-reference resolution and generic
interface checks. `builder.py` consumes these same resolved views when constructing
Pyomo objects; it no longer contains its own generic resolver.

```python
from multifidelity.model_language.resolution import Library

library = Library()
root = library.resolve("water_property_pair")
pair = root.relationships["evaluate"].models["states"]
inlet = pair.relationships["evaluate"].models["inlet"]
inlet.id  # "water_property_package"
inlet.structs["state"].variables["pressure"].unit  # "Pa"
```

`ResolvedModel.definition` is the shared typed JSON definition. Its `structs` and
its relationships' `constraints`/`connections` expose those same definition objects.
The resolved `models` collection maps local aliases directly to resolved model
views; each carries the generic arguments and path for its own reference context.
There is no per-reference `resolve()` call and no solver construction involved.

Relationship children are resolved on first access, then cached on that view.
This allows recursive definitions without eager unrolling and keeps unused
alternatives from forcing unrelated references to resolve. Errors in references
or generic interfaces surface when the corresponding children are accessed.
The builder accesses only its selected relationship at each level.

Treat definitions as unchanged while using a resolved view. After editing the
library, call `library.resolve(...)` again to obtain a fresh view. Resolved views
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
  "structs": {
    "inlet": {
      "direction": "input",
      "variables": {"pressure": {"unit": "Pa"}}
    },
    "outlet": {
      "direction": "output",
      "variables": {"pressure": {"unit": "Pa"}}
    }
  },
  "relationships": {
    "no_pressure_drop": {
      "models": {},
      "constraints": {
        "pressure": {
          "lhs": "outlet.pressure",
          "rhs": "inlet.pressure",
          "determines": "outlet.pressure"
        }
      },
      "connections": {}
    }
  }
}
```

Variable declarations support `unit` (default `dimensionless`), `value_type`
(currently only `real`) and `bounds: {"min": ..., "max": ...}`. Bounds are numerical
values in the declared unit. Without optional initial specifications, all
variables start free and without values.
Variables may declare ordered named `dimensions`; see indexed models below.
Input/output describes struct direction, not fixed/free solver status. No default
values, automatic input fixation, or permanent input/output role on variables is
introduced.

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
currently retain their scalar-only interface contract.

Run the complete pass-through pipe example with
`.venv/bin/python examples/indexed_models/build.py` from the repository root.
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
selections. Full instance documents remain deferred; pass their initial-value
list to the builder explicitly:

```python
from multifidelity.model_language import build_model, required_initial_values

selection = {"model": "tank", "relationship": "mixed"}
print(required_initial_values("tank", selection).keys())
# inventory.energy, inventory.level

model = build_model(
    "tank", selection,
    mode="dynamic",
    domain_values={"time": [0, 1000]},
    initial_values=[
        {"variable_path": "inventory.level", "value": 1, "unit": "m"},
        {"variable_path": "inventory.energy", "value": 125400000, "unit": "J"},
    ],
)
```

Each entry fixes only the first time point. An omitted `unit` uses the variable's
declared unit. Optional `at` selectors address non-time dimensions; for example,
`"at": {"cells": 2}` selects one cell. Without selectors the value is uniform
over all other axes. Overlaps, invalid selectors, nonfinite values, incompatible
units, and bound violations are rejected before any initial entries are fixed.
Paths use child aliases but omit the root model ID, like `required_inputs()`.

Initial values are optional during construction: a caller can apply them later
through Pyomo. The builder does not solve initialization or require that every
default initial output be fixed. An alternative set, such as initial level and
temperature instead of level and energy, can determine the starting state through
the physical equations. Checking independence and solving for consistent values
remain the caller's responsibility. Initial values passed in steady mode are an
error; steady operating specifications are applied separately.

For differentiation, backward differences leave the first rate outside the
discretization equations. Its supplied initial value closes that endpoint; other
equations at the initial time can still restrict it. Different discretization
schemes have different endpoint coverage. This first example uses backward
differences and does not promise arbitrary differentiation models are suitable
for PETSc forward integration.

### Mixed liquid tank example

The bundled `tank` model selects `mixed` in both modes. It has prescribed inlet
flow/temperature, a withdrawal-flow input, a heat-loss input, and scalar area,
density, heat capacity, and reference-temperature inputs. Outputs include level,
stored energy, temperature, rates, and the mixed outlet conditions:

```
rho * area * level_rate = inlet_flow - outlet_flow
energy_rate = inlet_flow * cp * (inlet_temperature - reference_temperature)
            - outlet_flow * cp * (temperature - reference_temperature) - heat_loss
energy = rho * area * level * cp * (temperature - reference_temperature)
```

This is a constant-density, constant-heat-capacity approximation with no phase
change, pressure dynamics, or kinetic/potential energy. Inlet flow and withdrawal
are nonnegative; flow reversal and empty-tank events are not modelled.

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
The initial-value list is saved separately in
`examples/dynamic_tank/initial_values.json`.

A relationship's `models` maps local aliases to definitions:

```json
"models": {
  "evaporator": {"model": "heat_exchanger"},
  "condenser": {"model": "heat_exchanger"}
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

Child outputs connect to child inputs. A parent input may feed a child input;
a child output may feed a parent output. Both structs must have exactly the same
field names with dimensionally compatible units. Connections convert units as
needed. General equations require authors to use consistent units; construction
checks dimensional consistency. Connecting structs does not fix either endpoint.

## Generic model parameters

A model can declare named dependencies on other model definitions. These select
**definitions**, while implementation documents still select **relationships**.
For example, a generic property-state pair declares:

```json
"model_parameters": {
  "FluidProperties": {
    "requires": {
      "state": {
        "direction": "input",
        "variables": {
          "pressure": {"unit": "Pa"},
          "enthalpy": {"unit": "J/kg"}
        }
      },
      "properties": {
        "direction": "output",
        "variables": {"temperature": {"unit": "K"}}
      }
    }
  }
}
```

Relationships use that dependency through named model references:

```json
"models": {
  "inlet": {"model_parameter": "FluidProperties"},
  "outlet": {"model_parameter": "FluidProperties"}
}
```

A containing relationship supplies all arguments at its concrete reference:

```json
"models": {
  "states": {
    "model": "property_pair",
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
`water_property_pair` or `heat_pump_flowsheet` to supply model arguments on its
child reference, then build the wrapper normally:

```bash
.venv/bin/python -m multifidelity.model_language water_property_pair \
  examples/model_language/water_property_pair_evaluate.json
```

The bundled `property_pair` exposes two pressure-enthalpy state inputs and two
property output structs (temperature, entropy, density, heat capacity and viscosity).
Its two property-model references use the same `FluidProperties` argument but
create separate occurrences. `water_property_pair` supplies the configured
`water_property_package`, which determines its coefficients internally. There
is no coefficient struct or coefficient plumbing on the pair.

## Implementations and construction

`implementation.py` defines the Pydantic `Implementation` root and recursive
`ImplementationSelection` type. Every node requires an explicit `relationship`;
`submodels` maps local child reference names to further selections. The root
requires `model`, while nested model IDs may be omitted because references already
determine them. Leaves have an empty `submodels` map by default.

```python
from multifidelity.model_language.implementation import Implementation

implementation = Implementation.model_validate_json(implementation_json)
implementation.submodels["states"].submodels["inlet"].relationship
```

These types check document shape only. They do not resolve references, check that
all children of a selected relationship are present, choose relationships
implicitly, or specify numerical values. Instance types remain deferred. The
builder still accepts the existing dictionary/JSON format; use
`implementation.model_dump(exclude_none=True)` to pass a typed selection to it
until direct integration is added.


An implementation identifies the root model and chooses its relationship:

```json
{
  "model": "heat_pump_flowsheet",
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
                  "relationship": "constant_properties",
                  "submodels": {}
                }
              }
            },
            "outlet_state": {
              "relationship": "constant_properties",
              "submodels": {
                "water": {
                  "relationship": "constant_properties",
                  "submodels": {}
                }
              }
            },
            "isentropic_state": {
              "relationship": "constant_properties",
              "submodels": {
                "water": {
                  "relationship": "constant_properties",
                  "submodels": {}
                }
              }
            }
          }
        },
        "condenser": {
          "relationship": "lumped",
          "submodels": {}
        },
        "subcooler": {
          "relationship": "lumped",
          "submodels": {}
        },
        "ihx": {
          "relationship": "lumped",
          "submodels": {}
        },
        "expansion_valve": {
          "relationship": "isenthalpic",
          "submodels": {}
        },
        "evaporator": {
          "relationship": "lumped",
          "submodels": {}
        },
        "source_inlet_state": {
          "relationship": "constant_properties",
          "submodels": {
            "water": {
              "relationship": "constant_properties",
              "submodels": {}
            }
          }
        },
        "source_outlet_state": {
          "relationship": "constant_properties",
          "submodels": {
            "water": {
              "relationship": "constant_properties",
              "submodels": {}
            }
          }
        },
        "sink_inlet_state": {
          "relationship": "constant_properties",
          "submodels": {
            "water": {
              "relationship": "constant_properties",
              "submodels": {}
            }
          }
        },
        "sink_outlet_state": {
          "relationship": "constant_properties",
          "submodels": {
            "water": {
              "relationship": "constant_properties",
              "submodels": {}
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
root.structs.source_inlet.flow
root.relationship.models.compressor.structs.performance.work
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
    "water_property_pair",
    "examples/model_language/water_property_pair_evaluate.json",
)
# Sorted dictionary: root-relative variable path -> typed Variable declaration.
required["states.inlet_state.pressure"].unit  # "Pa"

print_required_inputs(
    "water_property_pair",
    "examples/model_language/water_property_pair_evaluate.json",
)
```

The same listing is available from the command line:

```bash
.venv/bin/python -m multifidelity.model_language water_property_pair \
  examples/model_language/water_property_pair_evaluate.json --required-inputs
```

It prints entries such as `states.inlet_state.pressure [Pa]`, one variable per
line. Both methods accept a typed `Implementation`, a dictionary, or a JSON file
path, and an optional `library`. `print_required_inputs` accepts `file` for writing
to a stream. Paths use local model-reference aliases and omit the root model ID.

Every root input is required. At each selected relationship, its constraints'
`determines` declarations and each connection's destination fields supply child
inputs. Only the remaining child input variables are listed, recursively. A
constraint may supply one member of a struct while the other members remain
required. Repeated uses of the same definition have distinct paths. Inputs remain
required even if the selected equations do not use them.

The water-property-pair example requires only four variables: inlet and outlet
pressure and enthalpy. The pair supplies each package state through connections;
each configured package supplies its coefficients internally, so none are listed. Selecting a different
relationship can change the list; unselected alternatives are not traversed.

The query checks the implementation's root/model identities, explicit relationship
choices and complete child selections. It shares target coverage, duplicate
determination and connection direction/field checks with the backend. It does
not compile expressions, check equation units, establish mathematical determinacy,
create solver objects, fix variables, or fill any values. It relies on declared
`determines` targets; the Pyomo builder additionally verifies direct occurrence
or a dependency path through validated descendants. An incomplete definition such as the aggregate milk scaffold raises
its missing-output error instead of returning a misleading requirements list.
Instance data and applying specifications are deliberately left for the next step.

## Bundled models and provenance

`models/` contains reusable JSON definitions. Explicit construction selections
live in `examples/model_language/`; these are examples, not an instance framework.

| Model | Existing source and scope |
| --- | --- |
| `heat_exchanger` | Scalar lumped balance/conductance example inspired by `unit_models/heat_exchanger`; no segmented/distributed physics |
| `valve` | Isenthalpic pressure-drop equations |
| `pump`, `compressor` | Incompressible pump efficiency and isentropic compressor efficiency with generic property arguments |
| `pump_flowsheet`, `compressor_flowsheet` | Concrete water-package examples for the pressure changers |
| `thermal_conditioner` | Scalar stream heating balance |
| `water_state` | Pressure/temperature liquid state with affine enthalpy and constant density, heat capacity and viscosity |
| `water_state_ph`, `water_state_ps` | Pressure/enthalpy and pressure/entropy forms of the affine liquid-water model |
| `water_property_package`, `water_isentropic_package` | Configured PH and PS water-state wrappers supplying their own illustrative coefficients |
| `property_pair`, `water_property_pair` | Generic two-state property calculation and a concrete water specialization |
| `mixer`, `splitter` | Scalar mixing and prescribed split |
| `flash_separator`, `translator` | Topology scaffolds; no equilibrium, composition or basis conversion |
| `heat_pump_flowsheet` | Concrete wrapper supplying independent property-model arguments to `heat_pump` |
| `heat_pump` | Aggregate COP equations and the cycle topology from `unit_models/heat_pump/cycle.py`, including subcooler and IHX |
| `source_loop` | Valve/pump/evaporator/heater/tank recycle from `case_studies/sghp/source_loop.py` |
| `milk_evaporator` | Aggregate mass/energy balances and MVR topology from `unit_models/milk_evaporator/detailed.py` |
| `steam_generating_heat_pump` | All 19 equipment references and their stream connections from `case_studies/sghp/data/full_flowsheet_snapshot.json` |

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
scalar inputs, including the nested COP input; the cycle example requires 17,
with no specified COP. Neither requires external coefficient specifications. Parent relationships see
the same public interface regardless of the selected heat-pump relationship.


## Water state property model

`water_state` is an ordinary reusable model, not a new special type. Its
`constant_properties` relationship determines five output properties:

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

Like other model builds, this creates free variables without values or solving.
A caller must eventually specify both the state and the coefficients. For
example, an illustrative coefficient set is `T_ref = 298.15 K`,
`P_ref = 101325 Pa`, `h_ref = 104920.1198085 J/kg`, `cp = 4180 J/(kg K)`,
`rho = 997 kg/m³`, `mu = 0.00089 Pa s`, `s_ref = 367.1996421 J/(kg K)`,
and `alpha = 0.000257 / K`; these are not built-in defaults on raw state models.

An equipment relationship can reference separate `water_state` models for inlet
and outlet property calculations and determine their state inputs through
constraints or connections. These occurrences each own their variables. The generic
`property_pair` example instead uses the configured PH `water_property_package`. The heat pump uses independently configurable pressure-enthalpy
property models, described below; other equipment definitions are not yet
parameterized.

## Heat-pump hot-side and cold-side properties

`heat_pump` declares `HotSideProperties` for the sink and `ColdSideProperties`
for the source, plus `RefrigerantProperties` (PH) and `IsentropicProperties`
(PS) for the compressor reference calculation. Both relationships create
separate inlet/outlet package occurrences on each side. Pressure and enthalpy
are supplied from the corresponding public stream. Calculated temperature stays
on each internal package's `properties.temperature`; it is not a public heat-pump
output. The heat pump has no property-coefficient input structs.

Each argument must accept `state.pressure` and `state.enthalpy` and output
`properties.temperature`. No particular coefficient interface is required.
Additional fields are permitted; any unsupplied package-specific inputs remain
discoverable by `required_inputs()`.

`heat_pump_flowsheet` supplies `water_property_package` independently for the
source, sink and refrigerant PH arguments and `water_isentropic_package` for
the PS argument on its `heat_pump` reference. Both examples select this concrete
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

The existing heat-duty equations are unchanged: exchanger temperature differences
remain explicit inputs. Internal property calculations do not yet couple those
temperature differences to exchanger duties or introduce a Carnot relationship.

## Efficiency-based pressure changers

Both `pump` and `compressor` expose inlet/outlet mass flow, pressure and specific
enthalpy. They take `parameters.pressure_rise` and `parameters.efficiency`, and
calculate `performance.work` (positive work into the fluid). With the inlet
state specified, each concrete example needs five scalar specifications. No
power specification is required for these pressure-driven examples.

The pump's `incompressible` relationship follows IDAES's incompressible pump
assumption: `fluid_work = pressure_rise * outlet.flow / outlet_density`,
`efficiency * work = fluid_work`, and the adiabatic enthalpy-flow balance.
It takes a PH `FluidProperties` argument exposing density and reports fluid
work as `performance.fluid_work`.

The compressor's `isentropic` relationship uses PH `FluidProperties` for the
actual inlet/outlet states and PS `IsentropicProperties` for a hypothetical
reference state. The reference has the actual outlet pressure and inlet entropy.
`isentropic_work = inlet.flow * (reference_enthalpy - inlet.enthalpy)`,
`efficiency * work = isentropic_work`, and the adiabatic energy balance determine
actual work and outlet enthalpy. `performance.isentropic_work` is also exposed.
These two arguments represent input forms of the same fluid property model and
must use consistent coefficients, units and enthalpy/entropy reference conventions;
the structural interface check cannot establish their physical compatibility.

The configured `water_isentropic_package` wraps `water_state_ps`, which inverts
the same affine entropy equation:
`T = T_ref + T_ref / cp * (s - s_ref + alpha / rho * (P - P_ref))`.
It then evaluates enthalpy from pressure and temperature. All PT, PH and PS water
forms expose entropy; the pair exposes entropy alongside its other properties.
The default liquid-water examples demonstrate the equations and do not provide
validated vapor-compressor physics. Pressure ratio curves, motor efficiency,
heat loss and machinery performance maps are not included.

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
records to model instances and the specification-selection algorithm remain proposed.

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
| `variable_path` | Path to the variable in the model, using the existing model-variable path convention |
| `value` | Numerical observation, specification, estimate or assumed value |
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

```json
[
  {
    "id": "sink_temperature_observation",
    "tag": "TT101",
    "information_type": "sensor_reading",
    "variable_path": "sink_inlet.temperature",
    "value": 323.15,
    "unit": "K",
    "standard_deviation": 0.2,
    "trust_rank": 10
  },
  {
    "id": "sink_temperature_target",
    "tag": "TSP101",
    "information_type": "control_setpoint",
    "variable_path": "sink_inlet.temperature",
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

Records for one variable are alternatives. Normally use the highest-ranked
applicable record; retain lower-ranked records as fallbacks when the preferred
record cannot be used. They do not supply additional independent specifications
and are not averaged or fixed simultaneously. For the initial algorithm, selected
central values are fixed as an approximation, even for noisy records, with their
uncertainty retained in the audit trail. Fallback estimates used to close the
model are fixed assumptions, distinct from solver initial guesses.

See the [trust-ranked DM specification algorithm and separate experiment outlines](../../../research-ideas/information-directed-specification.md)
for structural candidate selection, auditable specification plans, and future
noise/conditioning studies. This algorithm is proposed, not yet implemented.
Whether tag definitions and timestamped values should be separated is also open;
no time-series schema or instance-application behavior is specified here.

### Information-table interface

```python
from multifidelity.model_language import InformationRecord, InformationTable

# JSON files contain an array of records, as above.
table = InformationTable.load_json("information.json")
# Or parse JSON text directly: InformationTable.from_json(json_text).

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
- **External Pyomo and machine-learning models:** Scalar symbolic providers are
  supported through external relationships; see the [how-to guide](custom-models.md).
  Broader indexed interfaces and model-specific initialization remain future work.
- **Parameter estimation:** How does estimation interact with our implementation
  selection and instance-specification methods, including information records,
  uncertainty and quantities of interest? What should be fixed, estimated or
  treated as an observation for a selected representation?

## Deferred decisions

- Continuous spatial domains and derivatives; automatic backend discretization
  configuration (time dynamics can use Pyomo's existing transformations).
- Default values, instance documents, fixed/free specifications and initial guesses.
- Replacing input specifications with selected output specifications.
- Detailed thermodynamics, component mixtures, shared material data, configurable
  equipment property dependencies, validated detailed equations and calibration.
- JSON Schema authoring support, definition version pinning and broader diagnostics.
- Solver integration, initialization algorithms and fidelity switching in place.

The builder checks selected references, scope, names, directions, connection fields,
equation units, explicit determination targets, duplicate determinations and missing
outputs. It is not yet a comprehensive document-schema validator.

## Heat-pump milk-evaporator flowsheet

`heat_pump_evaporator_flowsheet` combines the full
`steam_generating_heat_pump`, a direct-steam-injection `mixer`, and three
`milk_evaporator` occurrences (`effect_1` through `effect_3`). Milk passes
through the injection mixer and then each effect in order. Each effect has its
own exported `water_outlet_1`, `water_outlet_2`, or `water_outlet_3`; the last
effect supplies `milk_outlet`. The root inputs are `milk_inlet` and
`makeup_inlet` (fresh water for the SGHP warm-water loop).

The SGHP now exposes `steam_outlet` from its steam valve and `makeup_inlet`
to its warm-water mixer. These public boundaries allow composition without
reaching through its internal equipment. The injection mixer combines SGHP
steam with the milk feed by mass and enthalpy balances. Its pressure follows
its main milk inlet, as in the existing mixer definition; steam pressure
matching, condensation and milk composition are not modelled.

The topology follows the direct steam injection described in the older
[Python milk-effect case](../../../case_studies/milk_evaporator/README.md),
which starts after injection and builds only one effect. Three effects are an
explicit illustrative choice, not a recovered full-case configuration. They
are serial MVR effects, each with its own compressor, rather than a vapor-fed
multi-effect cascade. There is no condensate return to the SGHP.

```bash
.venv/bin/python -m multifidelity.model_language heat_pump_evaporator_flowsheet \
  examples/model_language/heat_pump_evaporator_flowsheet.json --required-inputs
```

The example selects the SGHP `flowsheet`, injection `balance`, and `detailed`
for all three milk effects. Each occurrence can select its implementation
independently, although the existing milk `aggregate` relationship is unclosed
and is rejected by construction validation. Equipment parameters and remaining
boundary inputs are discoverable with `--required-inputs`. This builds and
validates equation structure and units; it does not initialize or solve the
flowsheet, supply phase-equilibrium closure, or reproduce the calibrated case.

### Aggregate steam-generating heat pump

`steam_generating_heat_pump` offers `flowsheet` and `aggregate` relationships with
identical `makeup_inlet` and `steam_outlet` structs. The aggregate uses
`prescribed_cop` and `prescribed_power` children. It conserves mass, assumes
`steam_outlet.pressure = makeup_inlet.pressure`, and balances enthalpy flow with
added heat `COP * electrical_power`. Supply the makeup flow, pressure, enthalpy,
COP and electrical power as instance specifications. This illustrative closure
assumes nonzero makeup flow when computing outlet enthalpy; it does not guarantee
a vapor outlet, model saturation/latent heat explicitly, or expose source-side
heat extraction. The full flowsheet remains the default first relationship.

`examples/model_language/steam_generating_heat_pump_aggregate.json` selects the
aggregate and both children's `specified` relationships. It can also replace the
heat-pump child selection in the heat-pump evaporator flowsheet without changing
its steam connection. In the viewer, explore that child and select `aggregate`.
