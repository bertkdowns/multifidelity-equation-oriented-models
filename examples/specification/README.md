# Specify and solve a valve

Run from the repository root with the project environment and IPOPT available:

```bash
.venv/bin/python examples/specification/run.py
```

The example keeps three documents separate:

- `implementation.json` selects the valve's isenthalpic relationship.
- `information.json` holds available values, including an unused pressure fallback.
- `specification.json` chooses four information records to fix four variable families.

`run.py` builds the numerical model, applies the
specifications, checks zero degrees of freedom, and solves with IPOPT. No input
values are fixed elsewhere in the script. The measured pressure is used despite
its nonzero uncertainty: fixing the central value is the initial approximation.
The fallback remains unused because it is not selected by the document; this
example does not run a trust-ranking algorithm.

Expected result:

```json
{
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
