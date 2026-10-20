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
        "pressure": {"lhs": "outlet.pressure", "rhs": "inlet.pressure"}
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
There is no separate expression object, assignment, or `solves_for` hint. Derived
quantities are variables with defining equations. Supported arithmetic is
`+`, `-`, `*`, `/`, `**`, unary signs, numeric literals and parentheses.
References are `struct.variable` or `child_alias.struct.variable`. Units use
Pyomo unit names, for example `kg/s`, `J/kg`, `W/K`, and `dimensionless`.
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
state blocks. Property packages and process-specific adapters are future work.

## Bundled models and provenance

`models/` contains reusable JSON definitions. Explicit construction selections
live in `examples/model_language/`; these are examples, not an instance framework.

| Model | Existing source and scope |
| --- | --- |
| `heat_exchanger` | Scalar lumped balance/conductance example inspired by `unit_models/heat_exchanger`; no segmented/distributed physics |
| `valve`, `pump`, `compressor` | Basic scalar pressure/energy equations; no characteristic curves or isentropic property calculations |
| `thermal_conditioner` | Scalar stream heating balance |
| `mixer`, `splitter` | Scalar mixing and prescribed split |
| `flash_separator`, `translator` | Topology scaffolds; no equilibrium, composition or basis conversion |
| `heat_pump` | Aggregate COP equations and the cycle topology from `unit_models/heat_pump/cycle.py`, including subcooler and IHX |
| `source_loop` | Valve/pump/evaporator/heater/tank recycle from `case_studies/sghp/source_loop.py` |
| `milk_evaporator` | Aggregate mass/energy balances and MVR topology from `unit_models/milk_evaporator/detailed.py` |
| `steam_generating_heat_pump` | All 19 equipment references and their stream connections from `case_studies/sghp/data/full_flowsheet_snapshot.json` |

These definitions demonstrate construction, ownership, scope and topology. They
are **not numerical reproductions** of the existing cases. In particular, the milk
aggregate balances are unclosed, effectiveness is declared but not enforced, and
the detailed scaffold omits composition, phase carryover and property correlations.
The flash scaffold performs a prescribed split rather than phase separation.
Some composite inputs remain unused by these initial formulations. Closed loops
may contain redundant continuity constraints. Construction success and dimensional
consistency do not establish determinacy, physical validity or solvability.

## Deferred decisions

- Time/space dimensions, discretization and derivatives.
- Default values, instance documents, fixed/free specifications and initial guesses.
- Replacing input specifications with selected output specifications.
- Thermodynamics, component mixtures, validated detailed equations and calibration.
- JSON Schema authoring support, definition version pinning and broader diagnostics.
- Solver integration, initialization algorithms and fidelity switching in place.

The builder checks selected references, scope, names, directions, connection fields
and equation units. It is not yet a comprehensive document-schema validator.
