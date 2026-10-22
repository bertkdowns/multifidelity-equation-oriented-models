# JSON model specification language

This is a first construction-only implementation of the model language discussed
for recursive multifidelity modelling. It builds a selected equation hierarchy
inside an **IDAES** `FlowsheetBlock`, using Pyomo blocks, variables and constraints.
It does not solve, set initial guesses, fix inputs, or construct instance documents.
Here "build" means creating Python modelling objects, not numerical initialization.

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
structs, relationships and reference variants directly. Definitions retain model
IDs and generic parameter references; they do not yet resolve references, unroll
a tree, or select implementations independently of construction.

Document-shape validation rejects unknown fields, invalid component names,
missing required fields, unsupported variable types, invalid directions and
ambiguous reference kinds at load time, including in unselected alternatives.
Scope, generic interface compatibility, dimensions supported by the backend,
equation units and determination checks remain in the builder and apply to the
selected implementation. Implementation selections remain dictionaries for now.
Serialize definitions with `model_dump(by_alias=True)` or
`model_dump_json(by_alias=True)` to preserve JSON names (`Connection.from_` in
Python is `from` in JSON). Instance and implementation types are deferred.

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
values in the declared unit. All variables start free and without values.
Dimensions are reserved for future work; nonempty `dimensions` are rejected.
Input/output describes struct direction, not fixed/free solver status. No default
values, automatic input fixation, or permanent input/output role on variables is
introduced.

Constraints have `lhs` and `rhs` expression strings and always mean equality.
Each constraint also requires a `determines` variable reference.
There is no separate expression object, assignment, or `solves_for` hint. Derived
quantities are variables with defining equations. Supported arithmetic is
`+`, `-`, `*`, `/`, `**`, unary signs, numeric literals and parentheses.
References are `struct.variable` or `child_alias.struct.variable`. Units use
Pyomo unit names, for example `kg/s`, `J/kg`, `W/K`, and `dimensionless`.
`determines` is a validation contract, not an assignment or optional solver hint.
Its target must be a parent output or an immediate child input, and must occur
in the equation. It may appear on either side or inside an arithmetic expression.
For example, a balance `outlet.flow * outlet.enthalpy = ...` can determine
`outlet.enthalpy`. Parent inputs and child outputs cannot be targets here.

Each selected relationship must determine every parent output exactly once.
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
solutions require further analysis. Required-input reporting remains future work.

Python calls, subscripts, imports and arbitrary code are not supported; expression
strings are parsed using a restricted AST interpreter, never `eval`.

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
          "temperature": {"unit": "K"}
        }
      },
      "properties": {
        "direction": "output",
        "variables": {"enthalpy": {"unit": "J/kg"}}
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
      "FluidProperties": {"model": "water_state"}
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
`water_property_pair` to supply the arguments, then build it normally:

```bash
.venv/bin/python -m multifidelity.model_language water_property_pair \
  examples/model_language/water_property_pair_evaluate.json
```

The bundled `property_pair` exposes two state inputs, a coefficient input struct,
and two property output structs. Its two property-model references use the same
`FluidProperties` argument, with separate variables and explicit parameter
connections. The wrapper supplies `water_state`. This demonstrates the mechanism
without changing the existing equipment examples or adding bindings.

## Implementations and construction

An implementation identifies the root model and chooses its relationship:

```json
{
  "model": "heat_pump",
  "relationship": "cycle",
  "submodels": {
    "compressor": {"relationship": "energy_balance", "submodels": {}},
    "condenser": {"relationship": "lumped", "submodels": {}},
    "subcooler": {"relationship": "lumped", "submodels": {}},
    "ihx": {"relationship": "lumped", "submodels": {}},
    "expansion_valve": {"relationship": "isenthalpic", "submodels": {}},
    "evaporator": {"relationship": "lumped", "submodels": {}}
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
.venv/bin/python -m multifidelity.model_language heat_pump \
  examples/model_language/heat_pump_cycle.json
```

Or in Python:

```python
from multifidelity.model_language import Library, build_model

model = build_model(
    "heat_pump",
    "examples/model_language/heat_pump_cycle.json",
    library=Library(),  # Bundled definitions; or Library("my/models")
)
model.pprint()
```

The result is a `ConcreteModel` with `model.fs` as a steady IDAES flowsheet.
Its root definition is materialized at `model.fs.root`:

```python
root = model.fs.root
root.structs.source_inlet.flow
root.relationship.models.compressor.structs.parameters.work
root.relationship.constraints
root.relationship.connections
```

This is a generic equation structure inside IDAES, not an automatic translation
into the existing custom `UnitModelBlockData` equipment classes or thermodynamic
state blocks. Configurable property dependencies, shared material data, and
process-specific adapters are future work.

## Bundled models and provenance

`models/` contains reusable JSON definitions. Explicit construction selections
live in `examples/model_language/`; these are examples, not an instance framework.

| Model | Existing source and scope |
| --- | --- |
| `heat_exchanger` | Scalar lumped balance/conductance example inspired by `unit_models/heat_exchanger`; no segmented/distributed physics |
| `valve`, `pump`, `compressor` | Basic scalar pressure/energy equations; no characteristic curves or isentropic property calculations |
| `thermal_conditioner` | Scalar stream heating balance |
| `water_state` | Pressure/temperature liquid state with affine enthalpy and constant density, heat capacity and viscosity |
| `property_pair`, `water_property_pair` | Generic two-state property calculation and a concrete water specialization |
| `mixer`, `splitter` | Scalar mixing and prescribed split |
| `flash_separator`, `translator` | Topology scaffolds; no equilibrium, composition or basis conversion |
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

## Water state property model

`water_state` is an ordinary reusable model, not a new special type. Its
`constant_properties` relationship determines all four output properties:

- `state` (input): pressure in Pa and temperature in K.
- `parameters` (input): reference pressure, temperature and mass-specific enthalpy,
  plus constant density, mass-specific heat capacity and dynamic viscosity.
- `properties` (output): mass-specific enthalpy, density, mass-specific heat
  capacity, and dynamic viscosity.

The enthalpy equation is
`h = h_ref + cp * (T - T_ref) + (P - P_ref) / rho`.
The other three outputs equal their supplied coefficients. This is a simple
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
`rho = 997 kg/m³`, and `mu = 0.00089 Pa s`; these are not built-in defaults.

An equipment relationship can reference separate `water_state` models for inlet
and outlet property calculations and determine their state inputs through
constraints or connections. These occurrences each own their variables. The generic `property_pair` example uses this model through a configurable model
parameter. Existing equipment definitions are not yet parameterized, and shared
material coefficients remain undecided.

## Deferred decisions

- Time/space dimensions, discretization and derivatives.
- Default values, instance documents, fixed/free specifications and initial guesses.
- Replacing input specifications with selected output specifications.
- Detailed thermodynamics, component mixtures, shared material data, configurable
  equipment property dependencies, validated detailed equations and calibration.
- JSON Schema authoring support, definition version pinning and broader diagnostics.
- Solver integration, initialization algorithms and fidelity switching in place.

The builder checks selected references, scope, names, directions, connection fields,
equation units, explicit determination targets, duplicate determinations and missing
outputs. It is not yet a comprehensive document-schema validator.
