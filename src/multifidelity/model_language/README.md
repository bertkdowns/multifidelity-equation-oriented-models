# JSON model specification language

This is a first construction-only implementation of the model language discussed
for recursive multifidelity modelling. It builds a selected equation hierarchy
inside an **IDAES** `FlowsheetBlock`, using Pyomo blocks, variables and constraints.
It does not solve, set initial guesses, fix inputs, or construct instance documents.
Here "build" means creating Python modelling objects, not numerical initialization.

## Current blocking task: shared property-package bindings

Before extending the heat-pump property integration further, define how state
models bind to a shared, configured property package. Generic model arguments
currently select definitions; they do not bind repeated state occurrences to
shared coefficient values. The existing Python property packages already provide
shared parameter ownership through `state.params`, but the model language has
no equivalent mechanism yet.

The intended behaviour is to configure each property package once and let state
models reuse its parameters without passing coefficients through every containing
model. Hot-side and cold-side packages must remain independently selectable.
The heat pump should expose its stream flow, pressure and enthalpy, electrical
power and performance outputs; property coefficients and calculated temperatures
can remain internal to its selected relationship.

The current `hot_property_parameters`, `cold_property_parameters` and public
`*_properties` structs are provisional plumbing, not the intended final interface.
Resolve binding syntax, package ownership, scope and forwarding, and how shared
parameters appear in required-input discovery before revising that plumbing or
adding the Carnot-efficiency relationship.

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
inlet.id  # "water_state"
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
solutions require further analysis. Required inputs can be listed using the methods described below.

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
`water_property_pair` or `heat_pump_flowsheet` to supply model arguments on its
child reference, then build the wrapper normally:

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
      "model": "heat_pump",
      "relationship": "cycle",
      "submodels": {
        "compressor": {
          "model": "compressor",
          "relationship": "energy_balance",
          "submodels": {}
        },
        "condenser": {
          "model": "heat_exchanger",
          "relationship": "lumped",
          "submodels": {}
        },
        "subcooler": {
          "model": "heat_exchanger",
          "relationship": "lumped",
          "submodels": {}
        },
        "ihx": {
          "model": "heat_exchanger",
          "relationship": "lumped",
          "submodels": {}
        },
        "expansion_valve": {
          "model": "valve",
          "relationship": "isenthalpic",
          "submodels": {}
        },
        "evaporator": {
          "model": "heat_exchanger",
          "relationship": "lumped",
          "submodels": {}
        },
        "source_inlet_state": {
          "relationship": "constant_properties",
          "submodels": {}
        },
        "source_outlet_state": {
          "relationship": "constant_properties",
          "submodels": {}
        },
        "sink_inlet_state": {
          "relationship": "constant_properties",
          "submodels": {}
        },
        "sink_outlet_state": {
          "relationship": "constant_properties",
          "submodels": {}
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
root.relationship.models.compressor.structs.parameters.work
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

The water-property-pair example requires its two state structs and one parameter
struct: 10 variables. Its inlet/outlet property-model state and coefficient inputs
are supplied by connections and are not listed again. Selecting a different
relationship can change the list; unselected alternatives are not traversed.

The query checks the implementation's root/model identities, explicit relationship
choices and complete child selections. It shares target coverage, duplicate
determination and connection direction/field checks with the backend. It does
not compile expressions, check equation units, establish mathematical determinacy,
create solver objects, fix variables, or fill any values. It relies on declared
`determines` targets; the Pyomo builder still verifies their actual occurrence in
equations. An incomplete definition such as the aggregate milk scaffold raises
its missing-output error instead of returning a misleading requirements list.
Instance data and applying specifications are deliberately left for the next step.

## Bundled models and provenance

`models/` contains reusable JSON definitions. Explicit construction selections
live in `examples/model_language/`; these are examples, not an instance framework.

| Model | Existing source and scope |
| --- | --- |
| `heat_exchanger` | Scalar lumped balance/conductance example inspired by `unit_models/heat_exchanger`; no segmented/distributed physics |
| `valve`, `pump`, `compressor` | Basic scalar pressure/energy equations; no characteristic curves or isentropic property calculations |
| `thermal_conditioner` | Scalar stream heating balance |
| `water_state` | Pressure/temperature liquid state with affine enthalpy and constant density, heat capacity and viscosity |
| `water_state_ph` | Pressure/enthalpy inverse of `water_state`, calculating temperature with the same coefficients |
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
`performance.cop * parameters.electrical_power = performance.heating_duty`.
COP is undefined at zero electrical power; this construction-only language does
not enforce a nonzero operating specification.

With the bundled water property arguments, the aggregate example requires 20
scalar inputs, including the nested COP input; the cycle example requires 29,
with no specified COP. Both include 12 property coefficients (six per side). Parent relationships see
the same public interface regardless of the selected heat-pump relationship.


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
parameter. The heat pump uses independently configurable pressure-enthalpy
property models, described below; other equipment definitions are not yet
parameterized.

## Heat-pump hot-side and cold-side properties

`heat_pump` declares two independent generic parameters: `HotSideProperties`
for the sink and `ColdSideProperties` for the source. Both relationships create
separate inlet/outlet state occurrences on each side. Their pressure and enthalpy
are supplied from the corresponding stream; their temperature is exposed through
`source_inlet_properties`, `source_outlet_properties`, `sink_inlet_properties`,
and `sink_outlet_properties`. All four are output structs containing `temperature`.

Each argument must accept `state.pressure`, `state.enthalpy`, and the six
coefficients used by the existing constant-property interface; it must output
`properties.temperature`. Extra fields are permitted. The heat pump supplies
coefficients from `hot_property_parameters` and `cold_property_parameters`,
sharing a side's coefficients across its two state occurrences. Additional
package-specific inputs remain discoverable by `required_inputs()`.

`heat_pump_flowsheet` supplies `water_state_ph` for each argument on its
`heat_pump` reference. Both examples select this concrete flowsheet as the root;
its heat-pump child selects either `aggregate` or `cycle`. This is the
pressure-enthalpy inverse of `water_state`, using
`T = T_ref + (h - h_ref - (P - P_ref) / rho) / cp`, with nonzero `cp` and `rho`.
It remains a single-phase liquid approximation, not a refrigerant or steam
property package. Compatible models can be selected independently for each side.
When used as a submodel, the parent's heat-pump reference supplies these two
`model_arguments`; relationship selection remains in the implementation tree.

The existing heat-duty equations are unchanged: exchanger temperature differences
remain explicit inputs. Adding state properties does not yet couple them to
exchanger duties or introduce a Carnot relationship.

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
