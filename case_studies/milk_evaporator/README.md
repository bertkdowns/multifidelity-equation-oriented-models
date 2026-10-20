# Single milk-effect comparison

```bash
uv run python -m case_studies.milk_evaporator.example
uv run pytest -q tests/test_milk_evaporator.py
```

This example builds one `MilkEvaporator`, using the first effect of Ahuora's
**SGHP Milk Effect (BOIPOPT paper)** as its template. The input file
`data/first_effect.json` records selected stream values and equipment parameters
from revision 20, captured on 19 October 2026. These are current snapshot values,
not independently verified immutable SolveRun results. The live flowsheet was
inspected without edits or solves.

The feed is the first valve's inlet, after the original direct steam injection.
Neither steam injection, the heat pump, nor the other effects are constructed.
Milk thermodynamics come from `ahuora-compounds`, using the same configuration
with PH independent variables. The detailed equipment comes from `ahuora-builder`.
Power is fixed at 4.3 kW, operating pressure at 60 kPa, shared effectiveness at
0.75, exchanger U at 1000 W/(m² K), and compressor isentropic efficiency at 0.9.
Feed flow, composition and enthalpy are held fixed. Exchanger area and MVR
discharge pressure are calculated. The captured area of 10 m² is used only as an
initial guess, not a specification.

The aggregate example uses the same public effectiveness target, product enthalpy and water-pressure
reference values from the captured point, an assumed product-enthalpy/feed-enthalpy
slope of 0.1, and an assumed water-pressure/feed-enthalpy slope of
0.1 Pa/(J/mol). Other slope defaults remain explicit in the aggregate builder.
These are provisional local correlations for review, not fits over an operating
envelope or evidence of out-of-sample predictive accuracy.

Representative results:

| Output | Detailed | Aggregate |
| --- | ---: | ---: |
| Heat transferred to milk, kW | 134.728 | 134.118 |
| Milk product, kg/s | 0.01919 | 0.01995 |
| Product solids mass fraction | 0.2872 | 0.2791 |
| Water outlet pressure, kPa | 80.675 | 80.323 |
| Heat-recovery effectiveness | 0.75 (specified) | 0.75 (specified) |
| Exchanger area, m² | 9.685 (calculated) | not modeled |
| Overall energy residual, W | -5.040 | approximately zero |

Detailed residuals include the original translator's discarded numerical solids
carryover and the equal-temperature separator's energy discrepancy. The aggregate
model conserves water, solids and overall energy exactly. These differences are
reported rather than hidden with correction heat or mass terms.

Both formulations have zero remaining DOF under the common public specifications.
The tests exercise round-trip switching, an upstream connection, unit consistency,
balance diagnostics, perturbed aggregate inputs, and recovery after failed
initialization. No automatic fidelity-selection or calibration algorithm is added.
