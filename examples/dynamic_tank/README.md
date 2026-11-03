# Specify and simulate the same tank in steady and dynamic modes

```bash
.venv/bin/python examples/dynamic_tank/run.py
.venv/bin/python examples/dynamic_tank/run.py --backend petsc
```

Both commands require IPOPT; the second also requires the IDAES PETSc executable.
The example uses the [shared model-language terminology](../../src/multifidelity/model_language/terminology.md).

`make_tank()` constructs equations only. Its variables have no values or fixations.
For a dynamic run, `simulate()` discretizes the equations, calls `specify_tank()`
to apply all fixations, then sets numerical guesses separately and solves.

The information document holds all operating assumptions and starting values.
The dynamic specification document selects their IDs in two lists:

```json
{
  "specifications": [
    "tank_area", "density", "heat_capacity", "reference_temperature",
    "inlet_flow", "inlet_temperature", "heat_loss", "withdrawal_flow"
  ],
  "initial_values": ["tank_level", "starting_energy"]
}
```

`apply_specification(model, specification, information)` fixes operating values
throughout time, but fixes level (1 m) and energy (125400000 J) only at the first
time point. Later states remain free. The initial temperature follows from the
energy/level relation and is 303.15 K. Whole-family and initial conditions are
validated together before any fixing occurs.

The steady specification document instead fixes the tank level as an ordinary
operating condition, with no initial values. Withdrawal flow and temperature are
calculated from the steady balances. The same information record can therefore
serve different roles in separate specification documents.

The `inflow`, `outflow` and `loss` options in `specify_tank()` override assumptions
for bounded experiments; all values still go through information-record validation
and the same application method. `set_initial_guesses()` sets unfixed values only.
Alternative initial conditions can be applied explicitly, then use
`simulate(..., initial_values=[])` to omit the default initial selections.

Expected default results: steady level 1 m and temperature 333.15 K; the dynamic
backward-Euler run ends at level 1 m and temperature about 322.059 K after 1000 s.
PETSc approaches the continuous solution, about 322.114 K.

The former `initial_values.json` and `build_model(initial_values=...)` workflow is
removed. See the [initial specification API](../../src/multifidelity/model_language/README.md#initial-specifications)
for non-time-dimensional initial profiles and migration details.
