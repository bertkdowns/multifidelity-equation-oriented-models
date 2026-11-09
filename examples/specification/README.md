# Specify and solve a valve

Run from the repository root with the project environment and IPOPT available:

```bash
.venv/bin/python examples/specification/run.py
```

The example keeps three documents separate:

- `implementation.json` selects the valve's isenthalpic relationship.
- `information.json` holds eight records, including a pressure fallback and redundant outlet measurements.
- `specification.json` shows the expected four-record selection for comparison.
  `run.py` now generates this selection with `select_specification()`.

`run.py` builds the numerical model, applies the
specifications, checks zero degrees of freedom, and solves with IPOPT. No input
values are fixed elsewhere in the script. The measured pressure is used despite
its nonzero uncertainty: fixing the central value is the initial approximation.
The fallback and three outlet checks remain unused: the selector accepts four
independent records in trust order, reducing structural deficiency from four to
zero. It reports a reason for each skipped record. The default four records target
canonical inputs, so their `replacements` mapping is empty. If outlet information
is selected instead, the same selector automatically pairs it with an admissible
canonical input; no valve-specific replacement logic is needed.

Expected result:

```json
{
  "selected_records": ["inlet_flow", "pressure_measurement", "inlet_enthalpy", "valve_pressure_drop"],
  "replacements": {},
  "skipped_records": {
    "outlet_enthalpy_check": "already structurally determined",
    "outlet_flow_check": "already structurally determined",
    "outlet_pressure_check": "already structurally determined",
    "pressure_estimate": "lower-ranked alternative"
  },
  "degrees_of_freedom": 0,
  "termination_condition": "optimal",
  "outlet": {
    "flow_kg_per_s": 2.0,
    "pressure_Pa": 175000.0,
    "enthalpy_J_per_kg": 100000.0
  }
}
```

The valve conserves flow and enthalpy and subtracts 25 kPa from the 200 kPa inlet
pressure. Zero degrees of freedom is a useful check for this example; in general,
it does not prove structural independence or numerical solvability.

See the [model-language glossary](../../src/multifidelity/model_language/terminology.md)
and [specification API](../../src/multifidelity/model_language/README.md#specification-documents).
