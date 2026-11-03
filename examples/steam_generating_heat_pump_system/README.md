# Steam-generating heat-pump demonstration plant

One plant definition supports independent aggregate/cycle selections for the
SGHP and PHNIX heat pumps. The process reference is the
[SGHP thesis note](https://bertkdowns.github.io/thesis/notes/2ic55zb4xauos9xnvjtny5l/)
and [P&ID V22](https://bertkdowns.github.io/thesis/assets/SGHP%20P%26ID%20V22.pdf).
The current operating reference is
[Ahuora SGHP-DT-Spec, flowsheet 2450](https://ahuoratech.app/project/2450/flowsheet),
content revision 13, captured 4 November 2026 NZDT. It replaces the earlier
flowsheet 2384 reference.

## Construct the plant

Run from the repository root:

```bash
.venv/bin/python examples/steam_generating_heat_pump_system/build.py
.venv/bin/python examples/steam_generating_heat_pump_system/build.py --sghp cycle
.venv/bin/python examples/steam_generating_heat_pump_system/build.py --phnix cycle
.venv/bin/python examples/steam_generating_heat_pump_system/build.py --sghp cycle --phnix cycle
```

The scripts register the standard providers, construct equations, check units,
and report forward input coverage. Native Helmholtz functions and the Ahuora
property package dependency are required. The filename lists SGHP choice first,
PHNIX second. Construction does not fix values or solve the whole plant.

For the existing CLI, add provider registration explicitly:

```bash
.venv/bin/python -m multifidelity.model_language steam_generating_heat_pump_system \
  examples/steam_generating_heat_pump_system/cycle_cycle.json --standard-providers
```

## Equipment and property packages

| Circuit | Main path |
| --- | --- |
| Source water | SGHP evaporator → source valve → source pump → holdup tank → PHNIX sink side → electric heater → SGHP evaporator |
| Warm water | Makeup mixer → pipe pressure loss → warm-water pump → SGHP subcooler → splitter → cooling exchanger → makeup mixer |
| Hot water | Flash liquid → hot-water pump → mixer with warm makeup through its own valve → SGHP condenser → flash valve → flash tank |
| Steam | Flash vapor → steam valve → exported steam |

The three-circuit `steam_generating_heat_pump_unit` preserves source, hot and
warm stream interfaces across its aggregate and cycle relationships. Aggregate
heating duty includes condenser **and** subcooler heat. The detailed compressor
now uses **n-butane Helmholtz PH properties** for its inlet, actual outlet and
isentropic reference. PHNIX's cycle uses **propane Helmholtz PH properties**
for the same three state occurrences. Water pumps and
PHNIX water-side state models use Helmholtz water rather than affine coefficients.
PHNIX's named “Air Source” boundary still uses water properties, matching the
reference's explicit modelling assumption; no air-property model is implied.

Butane EOS data comes from the installed Ahuora package. Its data directory is
selected only during expression construction and the previous IDAES directory
is restored afterwards. The butane wrapper omits viscosity because those data
do not include a viscosity correlation. Isentropic reference enthalpy is a free
PH variable: the solver finds it by equating reference-state entropy to inlet
entropy at outlet pressure. There is one property-model argument per compressor,
with no separate pressure–entropy model or provider.

The older SGHP scaffold has been removed. This system owns the external water
loops and generic flash separator in every selection. All cycle exchangers now
use the appropriate water/butane/propane property states and counter-current
smoothed LMTD, rather than a supplied temperature difference. Captured temperature
difference observations now point to calculated driving-force outputs.

## Specify inlet temperatures

Streams retain mass flow, pressure and enthalpy internally. Separate PH property
blocks link to inlet pressure and enthalpy and expose temperature as a variable.
**Fix temperature on that property block and leave enthalpy free.** The coupled
Helmholtz equations then calculate enthalpy during the solve.

For example, an information record for the SGHP source-water inlet is:

```json
{
  "id": "source_temperature",
  "tag": "source.temperature",
  "information_type": "assumption",
  "variable_path": "sghp.source_inlet_state.properties.temperature",
  "value": 350.15,
  "unit": "K",
  "trust_rank": 8
}
```

Other paths include `sghp.hot_inlet_state.properties.temperature`,
`sghp.warm_inlet_state.properties.temperature`,
`phnix.sink_inlet_state.properties.temperature`, and the system-boundary
`makeup_state`, `cooling_water_state`, and `phnix_source_state` blocks.
These are direct state blocks: specify `makeup_state.state.pressure` and
`makeup_state.properties.temperature`, and connect `makeup_state.state` to downstream
equipment inputs. Reading a state input as a connection source does not supply it;
the state still needs operating specifications. Separate top-level input structs
and feed wrappers are unnecessary. Values are time-indexed, even for a single
steady operating point.
Use Kelvin in records; do not fix both temperature and enthalpy for the same
pressure unless another specification is deliberately released. For a saturated
two-phase inlet, pressure and temperature alone do not determine enthalpy: use
pressure and `properties.vapor_fraction` instead. Refrigerant compressor inlet
temperatures are available at `sghp.compressor.inlet_state.properties.temperature`
and `phnix.compressor.inlet_state.properties.temperature` in their cycle selections.

`required_inputs()` still reports the forward PH declaration contract; it is
not a requirement to fix enthalpy numerically. The specification selector uses
the actual equation structure and can select property temperature instead.

```bash
.venv/bin/python examples/steam_generating_heat_pump_system/build.py --sghp cycle --apply-reference
```

This applies a partial independent specification and reports missing information.
It reserves steam flow and total power for prediction. It does not fill missing
closures or claim that the complete recirculating plant has been solved.

## Phase separator

`flash_separator.phase_split` takes a `FluidProperties` argument and has one
inlet and two outlets. This system selects Helmholtz water; the model itself
also works with other pure-fluid packages supplying phase enthalpies and quality.
The routing and phase-energy balances are JSON equations; they no longer build
a water-specific native separator. Outlet PH states use the selected package.

The two inputs are fractions of **each inlet phase routed to the outlet named
`liquid`**:

| Input | Normal steam/condensate separation |
| --- | --- |
| `flash_tank.parameters.liquid_to_liquid` | 1: send all liquid to condensate |
| `flash_tank.parameters.vapor_to_liquid` | 0: send no vapor to condensate |

The outlet named `vapor` receives the complementary fractions. Both fractions
are bounded from 0 to 1. Intermediate settings can send mixtures to both outlets;
these are phase-routing fractions, not prescribed outlet vapor qualities.
Calculated qualities and temperatures are exposed on `liquid_properties` and
`vapor_properties`. No outlet enthalpy specification is needed. Empty outlets use
the corresponding inlet phase enthalpy as a reporting convention, with zero mass
and energy flux. Simple liquid-water approximations cannot supply two-phase
enthalpies and are rejected as flash arguments.

## Replay the operating point

```bash
.venv/bin/python examples/steam_generating_heat_pump_system/replay.py --with-flash
```

Requires IPOPT. The SGHP aggregate replay fixes inlet flows, pressures and
**property-block temperatures**, captured work, warm-water duty and a COP
calibrated from that same reference point. Inlet/outlet enthalpies remain free.
Numerical guesses are set separately from specifications.

The captured duties are 46.7606715 kW at the condenser and 20.6947322 kW at the
subcooler, with 12.7558356 kW compressor work: total heating COP is 5.288200.
The source-water pressure is overridden locally to **2 bar absolute** while its
inlet temperature remains 77 °C. Its enthalpy is now determined by the PH solve,
not the earlier precomputed TP value or high-pressure captured enthalpy.

The solved hot-water outlet passes through an isenthalpic letdown to the generic
phase separator at 200 kPa. With ideal routing, this gives approximately
**72.9501 kg/h steam** and **0.8101999 kg/s condensate**. Phase enthalpies are
calculated by Helmholtz, rather than copied from the captured outlet records.
The replay is sequential and does not close the surrounding plant recycles.
COP is calibrated at this point; agreement is not independent prediction validation.

## Evidence and remaining differences

- `ahuora_reference.json` retains current stored values, units, display text,
  formulas, replacements, ports and tags. These are not live measurements or
  immutable successful SolveRun results.
- `information.json` contains applicable configuration, temperatures, phase routing
  and explicitly labelled frozen manipulated/design values.
- `reference_observations.json` keeps captured outputs separate for comparison;
  they are not automatically fixed by the selector.
- `value_provenance.json` records source identities, transformations and overrides.
- `sghp_replay_information.json` and `sghp_replay_specification.json` define the
  temperature-based unit replay; `flash_replay_information.json` supplies pressure
  and routing fractions, not phase enthalpies.
- `reference_checks.json` records the original return-cut comparisons.

Original source pressure 651751.6546 kPa remains in the raw capture for audit;
the local override does not edit Ahuora. In the reference, the hot-water return
is 0.8257525 kg/s while the independent condenser inlet is 0.8304639 kg/s.
Makeup is about 55.9892 kg/h versus 72.9501 kg/h steam. A consistent complete
steady operating specification is still needed to close that mismatch.

The reference has no inline source electric heater or holdup tank; its `Heater1`
is a separate refrigerant state calculation, so its values are not copied into
those local P&ID elements. Exchangers use supplied conductance with LMTD
calculated from the four property-package temperatures. The captured IHX hot/cold
names are opposite the local convention, so the stored temperature-difference
observation is sign-adjusted for comparison; it is no longer an exchanger input. Bypasses, detailed refrigerant
inventory, relief devices and control dynamics remain omitted or lumped.
Using actual refrigerant properties improves the thermodynamics; it does not
make the complete selected cycle a numerically validated plant model.
