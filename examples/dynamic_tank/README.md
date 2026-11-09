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
The dynamic specification document selects their IDs and pairs operating replacements:

```json
{
  "specifications": [
    "tank_area", "tank_pressure", "inlet_pressure",
    "inlet_flow", "inlet_temperature", "heat_loss", "withdrawal_flow"
  ],
  "replacements": {"inlet_temperature": "tank.inlet.enthalpy"},
  "initial_values": ["tank_level", "starting_energy"]
}
```

`apply_specification(model, specification, information)` fixes operating values
throughout time, but fixes level (1 m) and internal energy (125341334.4490745 J) only at the first
time point. Later states remain free. The initial temperature follows from the
energy/level relation and is 303.15 K. Whole-family and initial conditions are
validated together before any fixing occurs.

The steady specification document instead fixes the tank level as an ordinary
operating condition, with no initial values. Withdrawal flow and temperature are
calculated from the steady balances. Its replacement mapping pairs `tank_level`
with `tank.withdrawal.flow` and `inlet_temperature` with `tank.inlet.enthalpy`.
The same information record can therefore
serve different roles in separate specification documents.

The `inflow`, `outflow` and `loss` options in `specify_tank()` override assumptions
for bounded experiments; all values still go through information-record validation
and the same application method. `set_initial_guesses()` sets unfixed values only.
Alternative initial conditions can be applied explicitly, then use
`simulate(..., initial_values=[])` to omit the default initial selections.

Expected default results: steady level 1 m and temperature 333.15 K; the dynamic
backward-Euler run ends at level 1 m and temperature about 322.092 K after 1000 s.
PETSc approaches the continuous solution, about 322.147 K.

The former `initial_values.json` and `build_model(initial_values=...)` workflow is
removed. See the [initial specification API](../../src/multifidelity/model_language/README.md#initial-specifications)
for non-time-dimensional initial profiles and migration details.

The generic tank uses PH ports and differentiated mass/internal-energy inventories.
`make_tank()` builds the concrete `tank_flowsheet` wrapper, with the tank at `tank`.
Temperature specifications use `tank.inlet_state.properties.temperature`; density
comes from the contents property package rather than a tank parameter. Level is
calculated from mass divided by current density and area. The example's affine
water package has density 997 kg/m³ and includes pressure work in PH enthalpy.
The stored internal-energy relation is U = m h - P V.

Running `run.py` also writes `steady_workspace.json` and `dynamic_workspace.json`
for **Open workspace** in the viewer. Each contains the selected implementation,
information records, and the solved snapshot with its actual time grid. Local
layout/navigation preferences and model definitions are not included.
