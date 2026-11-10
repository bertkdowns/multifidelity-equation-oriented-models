# Steam-generating heat-pump demonstration plant

One plant definition supports independent aggregate/cycle selections for the
SGHP and PHNIX heat pumps. The process reference is the
[SGHP thesis note](https://bertkdowns.github.io/thesis/notes/2ic55zb4xauos9xnvjtny5l/)
and [P&ID V22](https://bertkdowns.github.io/thesis/assets/SGHP%20P%26ID%20V22.pdf).
The current operating reference is
[Ahuora SGHP-DT-Spec, flowsheet 2450](https://ahuoratech.app/project/2450/flowsheet),
content revision 13, captured 4 November 2026 NZDT. It replaces the earlier
flowsheet 2384 reference.

For the current comparison with identical operating specifications, run
`compare_fidelities.py` and use the `common_*` artifacts described at the end of
this document. The earlier attempt scripts and reports preserve the sequence of
operating-specification experiments.

The first dynamic thermal demonstration is also available: run
`run_thermal_dynamics.py` and open `thermal_step_workspace.json`. It uses three
initial 100-litre water inventories and a PHNIX power step; see the dynamics
section below for assumptions and verification.

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
| Source water | SGHP evaporator → source valve → source pump → holdup tank → PHNIX sink side → SGHP evaporator |
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

## Complete-system solve attempt without initialization

`attempt_information.json` and `attempt_specification.json` capture the requested
aggregate/aggregate operating point: source tank duty zero, steam export 1 bar
absolute, warm loop and warm makeup 2 bar absolute, and makeup 55.99 kg/h.
Steam flow remains a prediction constrained by the steady mass balances. The
captured splitter fraction is released because it becomes dependent on this
specification. Other applicable reference specifications are retained.

```bash
.venv/bin/python examples/steam_generating_heat_pump_system/attempt_solve.py
```

The original attempt assigned no numerical guesses. The model was structurally complete with zero
degrees of freedom, but IPOPT failed at its initial equation evaluation before any
iterations. The diagnostic identifies `source_pump.fluid_work`: its division by
the unset outlet-state density evaluates as 0/0. `attempt_result.json` records the
outcome. This is a starting-point evaluation failure, not a demonstrated
infeasibility of the requested operating conditions. Add `--diagnostic` to stop
on the first invalid evaluation with the symbolic constraint name.

Reusable declaration defaults now provide guesses during construction. A later
attempt using these defaults and unused information moved past the 0/0 failure,
but reached the 500-iteration limit without convergence; see
`attempt_with_defaults_result.json`. The original result remains historical
evidence rather than the expected outcome of rerunning with current defaults.

## Bottom-up initialisation attempt

```bash
.venv/bin/python examples/steam_generating_heat_pump_system/attempt_bottom_up.py
```

This applies the same saved operating specification, seeds unused information,
and invokes `initialize_model()`. It writes `attempt_bottom_up_result.json` and
returns a nonzero exit status if a stage fails. No replay helpers, case-specific
guesses, or changes to the operating specification are applied.

The prescribed-COP model defaults to an unfixed guess of 3 and the prescribed-power
model to 1000 W (1 kW). The thermal-conditioner model defaults to 1 kg/s,
100 kPa, 10000 J/kg and zero heat duty. These leaves initialise successfully
and their temporary fixes are released.

Before numerical input ranking, the attempt failed at `sghp.source_inlet_state`
after temporarily fixing enthalpy and leaving pressure to reconcile temperature.
The scaled null-space selection implemented in `0eb5090` resolves that failure:
it fixes flow and pressure and leaves enthalpy free. The source state initialises
at 200 kPa and 77 degrees C with enthalpy 322523.13 J/kg. The hot and warm inlet
states also initialise, making nine successful stages before reaching `sghp`.
These are local initialisation results, not a converged plant solution.

The first scaled attempt stopped at the SGHP parent, with eight remaining local
structural degrees of freedom. Its own inlet structs still had unset free values
despite the completed child state blocks, so there was no eligible guessed
boundary input to fix. The parent was not sent to IPOPT.

An additional structural inspection on a clone, recorded in commit `170de47`, copied
child state guesses to the parent inlets and permitted five independent boundary fixes,
but left three freedoms. Fixing the descendant COP, electrical-power and
warm-water heat-duty inputs closed those remaining freedoms. Those extra fixes
were diagnostic only; they were not applied to the operating model or enabled
as automatic parent-stage candidates in that version.

The initializer now includes descendant public inputs that are not connected to
or defined by their parent. Supplied child inputs remain excluded at ancestor
stages. To avoid needing value propagation, the SGHP unit declares stream guesses
of 1 kg/s, 200 kPa and 100 kJ/kg on its own inlet/outlet structs, plus coherent
performance guesses: COP 3, electrical power 1 kW, heating/hot-water duty 3 kW,
warm-water duty zero and cooling duty 2 kW. These are unfixed initial guesses,
and operating specifications still take precedence.

With this change, all SGHP child stages and the SGHP parent initialise successfully.
The local SGHP closure uses its five independent inlet choices and the descendant
COP, power and warm-water-duty inputs; all temporary fixes are released afterwards.
The aggregate heat-pump model now also declares stream guesses of 1 kg/s,
200 kPa and 100 kJ/kg, with COP 3, electrical power 1 kW, heating duty 3 kW
and cooling duty 2 kW. The remaining loop equipment has reusable stream,
phase-routing and performance guesses; exchanger guesses give positive terminal
temperature differences. These guesses are unfixed and do not replace operating
specifications.

All 62 component stages now initialise. The final whole-plant stage has no missing
starting values, but its scaled Jacobian has numerical rank 954 against expected
structural rank 957. The root solver is therefore not called. Inspection of the
three near-zero singular directions involves flash-mixture equations and closed-loop
mass balances; this local diagnostic does not establish three separate physical
causes or whole-plant infeasibility. The report records the attempt and local states,
not a converged plant solution. Guess propagation remains deferred.

An explicit follow-up experiment, `attempt_rank_deficient_solve.py`, passes the
same initialized plant to IPOPT despite the root rank check. The normal initializer
is unchanged. IPOPT ran 216 iterations and exited with restoration failure; no
solution was returned for loading. Its final scaled constraint violation was
1.90e-8, but the unscaled violation was 9.73e5, and the log repeatedly reported
invalid scaling factors. This attempt does not establish feasibility or whether
the rank deficiency is only local. The result JSON and solver log are saved beside
the script. Residuals labelled `retained` describe the unchanged pre-solve values
when no solver solution is available.

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

The reference has no holdup tank; its `Heater1` is a separate refrigerant state
calculation. The local source tank remains, while the previously included inline
electric heater has been removed to match the real plant. Exchangers use supplied conductance with LMTD
calculated from the four property-package temperatures. The captured IHX hot/cold
names are opposite the local convention, so the stored temperature-difference
observation is sign-adjusted for comparison; it is no longer an exchanger input. Bypasses, detailed refrigerant
inventory, relief devices and control dynamics remain omitted or lumped.
Using actual refrigerant properties improves the thermodynamics; it does not
make the complete selected cycle a numerically validated plant model.

## Scaling and specification diagnostics

Run `inspect_scaling.py` to audit exported factors and inspect the raw AMPL primal
vector after the failed root solve. This vector is diagnostic evidence, not an
accepted solution. The saved `scaling_inspection_result.json` shows that all
exported factors are finite and positive. Variable factors range from 1e-5 to
1000. The vapor-mixture enthalpy equation has an automatic factor of
3.693e-42: differentiating its flow-weighted enthalpy near an empty stream
produces enormous derivatives, so reciprocal Jacobian row normalization almost
erases that equation. At the failed iterate its residual is 973207.98 J/kg;
the next largest numerical residual is only 2.42e-5 W in total power. Residuals
with different units should not be compared as a physical norm.

The warning itself comes from IPOPT's MC19 symmetric linear-system scaling,
which is separate from user NLP scaling. In the installed version's
[MC19 interface](https://raw.githubusercontent.com/coin-or/Ipopt/releases/3.13.2/src/Algorithm/LinearSolvers/IpMc19TSymScalingMethod.cpp),
the warning is triggered by a nonfinite sum of computed factors or a maximum
factor above 1e40. It does not identify a particular model variable. A controlled
retry with only `linear_system_scaling=none` removed the warning but retained the
same large enthalpy residual and restoration failure. No general scaling policy
has been changed by these experiments.

`diagnose_specifications.py` uses the reusable `relax_specifications` method to
soften all 31 selected information-table fixes on an independent clone. Physical
equations and bounds stay hard. The saved default attempt reached its CPU limit;
its makeup-flow adjustment is provisional and does not identify a bad record.
Run with `--vapor-enthalpy-scale 1e-5` for the controlled experiment replacing only
the problematic equation scale. That relaxation reaches IPOPT's acceptable
level. The largest weighted deviations are PHNIX sink inlet temperature
(75.3837 to 76.1925 degrees C) and SGHP source inlet temperature (77 to 76.1912
degrees C). All record weights are 1, with deviations normalized using the
variable scales. These are joint reconciliation changes under those weights,
not proof that either measurement is wrong. See the result JSON for residuals
and operating values before interpreting this as a physical operating state.

The acceptable-level relaxation is **not a physically credible operating point**:
source circulation is 5.879e7 kg/s, SGHP COP is -8837.62 and electrical power is
-6.44 W. The current model bounds admit these values. Steam production is about
55.993 kg/h, but that does not validate the rest of the state. The largest raw
energy-balance residuals are 0.00390625 W; even small equation residuals and a
solver optimality flag do not enforce physical limits that were never declared.
Meaningful operating bounds and an empty-stream scaling policy need to be
settled before treating the slack ranking as a diagnosis of conflicting data.

## Current attempt: prescribed flash outlet compositions

The current `attempt_information.json` and `attempt_specification.json` replace
phase-recovery specifications with outlet vapor fractions: 0.01 in the liquid
outlet and 0.99 in the vapor outlet. These specify compositions, not recovery
percentages or total outlet flow fractions. The two phase-routing variables are
free. Captured reference information and the earlier diagnostic snapshots above
retain their original settings.

Unused information records provide two-phase enthalpy and routing guesses; they
are not fixed operating specifications. The local flash Jacobian is full rank
after closure, but its solve fails with the initializer's temporary inlet-enthalpy
and liquid-routing fixes. `attempt_outlet_quality.py` therefore also tries the
complete plant without those temporary fixes. The initial root numerical rank
improves from 954/957 to 956/957. IPOPT converges to a locally infeasible point,
with the largest residuals in the flash liquid state's vapor-fraction equation
(0.005797) and its binding (0.001879). This is not proof of global infeasibility.
The failed iterate also retains negative SGHP COP and electrical power; it is
not an operating solution. The current bottom-up and whole-plant reports are
saved as `attempt_bottom_up_result.json` and `attempt_outlet_quality_result.json`.

## Current topology: no electric source heater

The inline source heater has been removed from the shared plant definition and
all four fidelity selections, including the nested plant example. PHNIX sink
outlet connects directly to SGHP source inlet. Total electrical power is the sum
of the two heat pumps and the circulation pumps. The source tank remains with
its specified zero heat duty.

The preceding heater-containing numerical results are historical snapshots.
The current `attempt_outlet_quality_result.json` records the no-heater retry:
951 equality rows, 950 free variables and numerical column rank 950. IPOPT stops
before iterating with too few degrees of freedom. A separate linear-row QR
inspection finds 685 linear rows of rank 684; the redundant row can be represented
by `source_evaporator_feed.flow`. This is the duplicated continuity relation around
the source recycle. A trial using IPOPT dependency detection was rejected because
the installed executable does not recognize `dependency_detector` or
`dependency_detection_with_rhs`. No physical balance was disabled in the model.

## Current successful solve: explicit mass recycle definition

The source connection now passes through `source_mass_recycle`, an instance of
`mass_recycle_definition`. It copies pressure and enthalpy and obtains outlet
flow from its separate `flow_definition.flow` input. The ordinary inlet flow is
unused within the block; the other source-loop mass balances still enforce
continuity. The separate flow input is left free. All four plant fidelity
selections and the nested plant example include the block. No electric heater
or solve-time equation removal is involved.

The operating attempt now fixes SGHP COP to 5.2881995212, taken as an assumption
from `replay_calibrated_cop` in the earlier unit replay. It releases the captured
hot-water inlet temperature, retaining that record as a starting guess. The new
flash outlet compositions determine different return/mixing states, so fixing
that old inlet temperature as well was inappropriate for this demonstration.
The original captured `information.json` remains unchanged; active choices and
guesses are in `attempt_information.json` and `attempt_specification.json`.
Additional phase-mixture flow/enthalpy guesses make the flash child stages
consistent with two-phase outlet specifications during local initialization.

The standard `attempt_bottom_up.py` run now succeeds through all 63 stages.
The root Jacobian has 957 rows, 957 columns and numerical rank 957. Its complete
model maximum scaled constraint violation is 2.324e-10. Source circulation is
8.06372 kg/s, steam export is 55.99 kg/h, SGHP electrical power is about 12.7564 kW,
and its calculated hot-water inlet temperature is 128.57984 degrees C.
The existing local definition checks remain enabled: they validate coverage and
dependencies, while global independence is established by the structural and
numerical analyses. Earlier failure snapshots above describe superseded
configurations.

The current calibrated-COP assumption also predicts a two-phase warm-water
outlet: the cooling exchanger hot inlet is 120.23252 degrees C with vapor
fraction 0.336265. The equations are satisfied, but this is not a validated
real-plant operating point. A liquid-only warm loop would require further
operating-specification choices; no extra phase or temperature constraint has
been silently imposed here.

## Current COP 4 trial

The active operating attempt now uses the user's estimated SGHP COP of 4 via
`attempt_sghp_operating_cop`, replacing the earlier calibrated-COP assumption.
All other fixed operating values are unchanged. The full plant still solves at
rank 957/957 and steam export 55.99 kg/h. Source circulation remains 8.06372 kg/s.
SGHP electrical power increases to 18.23406 kW because PHNIX supplies a fixed
source-loop duty: `P = Q_source / (COP - 1)`.

This trial finds an unsuitable warm-loop operating state: the cooling exchanger
hot inlet is 124.84802 degrees C and entirely vapor. SGHP warm-water duty is
73.60663 kW, whereas total heating duty is 72.93624 kW; the unconstrained
aggregate hot-side duty is therefore -0.67039 kW. COP 4 alone does not select the
intended heating operation. Fixing measured SGHP electrical power as well, while
releasing PHNIX power, is a possible next operating-specification choice. Those
additional changes have not been applied in this trial.

## Viewing the saved numerical solution

`attempt_bottom_up.py` now also exports `results.json` using the reusable
`ResultsDocument` format. It contains all 671 public variable families with
values, units, coordinates and fixed/free state, the chosen implementation,
specification IDs and explicit solve status. Upload it in the viewer's
**Results** tab. The other result JSON files in this folder remain diagnostic
reports and do not use the upload format.

## Detailed SGHP cycle trial before the refrigerant recycle cut

Run `.venv/bin/python examples/steam_generating_heat_pump_system/attempt_cycle.py`
to try `cycle_aggregate.json` with the current shared plant specifications.
The aggregate-only fixed COP is removed; four captured exchanger conductances
and compressor efficiency 0.75 are fixed instead. COP is a cycle prediction.
The resulting plant has zero structural degrees of freedom.

The trial did not converge: 53 child stages initialized, then the SGHP stage
reported numerical rank 926 for 927 equations (935 free variables before its
eight temporary input fixes). A direct IPOPT attempt bypassing that rank check
reached 1000 iterations without convergence; its largest retained constraint
violation was approximately 1.09e7. These values are failed iterates, not an
operating solution. The closed refrigerant continuity loop is a candidate
source of exact redundancy and needs investigation before comparison.

`cycle_attempt_specification.json`, `cycle_attempt_result.json`, and
`cycle_results.json` preserve the trial separately from the successful aggregate
case. The results snapshot is explicitly marked failed.

## Refrigerant mass recycle cut and retry

The SGHP cycle now routes `ihx.cold_outlet` through
`refrigerant_mass_recycle` before the compressor inlet. This uses the same
`mass_recycle_definition` as the source loop: pressure and enthalpy pass through;
a separate free flow input defines the downstream flow. Remaining component
balances enforce continuity around the recycle without the duplicate row.
Both SGHP cycle selections and the nested plant example include the block.

The cut exposes one additional structural degree of freedom. For the saved
retry, `attempt_cycle.py` freezes the captured compressor pressure rise at
2011.6863921285753 kPa as an explicit trial operating assumption (reference
property value 630426); it is not a live measurement.
`cycle_attempt_information.json` contains this record alongside the shared
operating information. The resulting complete plant again has zero structural
degrees of freedom. COP and compressor power remain predictions.

The mass-continuity rank deficiency is removed: the unclosed SGHP Jacobian has
933 independent rows. However, local initialization still fails after choosing
temporary boundary fixes: it fixes expansion-valve pressure drop last, although
that drop is already tied to the specified compressor pressure rise around the
closed pressure loop. The closed local Jacobian is rank 932 of 933. This is an
input-closure limitation; it does not establish a redundant equation in the
complete specified plant. All 54 preceding child stages initialize.

A direct whole-plant IPOPT retry also fails, reaching 1000 iterations with a
maximum retained constraint violation of approximately 1.09e7. No converged
cycle operating point or meaningful COP comparison is available. The trial
report and failed results snapshot are saved separately from the successful
aggregate case.

## Cycle specification-relaxation diagnosis

`diagnose_cycle_specifications.py` uses the reusable `relax_specifications`
method with variable scales and equal record weights. Run the successful
diagnostic with:

```sh
OPENBLAS_NUM_THREADS=1 .venv/bin/python examples/steam_generating_heat_pump_system/diagnose_cycle_specifications.py --coherent-guesses
```

Default guesses and captured-butane guesses alone both reached iteration limits,
so their slack rankings are explicitly marked unusable. The coherent diagnostic
uses the successful aggregate `results.json` for shared public starting values,
captured butane PH states, and direct evaluation of native property definitions.
These are diagnostic starting values, not a new library initialization procedure
or additional fixed specifications. Existing aggregate results and operating
information are unchanged.

The coherent relaxed optimization converges with maximum scaled violation
3.76e-10 and maximum raw violation 3.76e-5 J/kg. No negative public flows,
electrical powers or conductances, or efficiencies outside (0,1], were found.
The dominant change is makeup flow 55.99 -> 70.2251 kg/h, accounting for 99.19%
of the sum of weighted squared scaled deviations. The predicted SGHP COP is
4.59859 and power 15.2001 kW. Other adjustments are small (for example, source
inlet temperature +0.0416 K and liquid-outlet vapor fraction 0.01 -> 0.00975784).
This ranking depends on the declared variable scales; it does not identify a
unique erroneous measurement.

Two controlled verification solves follow the relaxed solve:

- Restore every original selected specification except makeup flow: IPOPT
  converges at **70.3421766 kg/h steam/makeup**, COP **4.5839006**, maximum scaled
  violation 9.22e-10. Only makeup flow differs from its selected target.
- Restore makeup flow to **55.99 kg/h** as well: IPOPT reports local infeasibility.
  Its largest scaled residual is a condenser water-side mass balance of
  0.003759 kg/s; this is a failed iterate, not a valid steam operating point.

The evidence therefore points to a conflict between the imposed 55.99 kg/h
makeup/steam rate and the other fixed heat-input/equipment conditions on this
solution branch. It does not establish global mathematical infeasibility or
prove that the user-supplied flow is wrong. Changing heat input rather than the
steam target is another reconciliation option, not tested or applied here.

`cycle_specification_relaxation_coherent_result.json` contains the converged
ranking and equation residuals; its companion `_results.json` can be uploaded
in the viewer as a relaxed diagnostic snapshot. `cycle_relaxation_verification.json`
contains both controlled checks. The fixed operating case remains unchanged.

## Fixed SGHP electrical power instead of makeup flow

The current `attempt_cycle.py` replaces `attempt_makeup_mass_flow` with the
SGHP electrical-power specification. Makeup flow is free and the 55.99 kg/h
information record remains a starting guess. The initial power trial used the captured
12.755835603752978 kW (`reference_sghp_performance_electrical_power`). The working
default is now 15.20 kW; an explicit `--power-kw` argument overrides it.
Both PHNIX power and the previously captured compressor pressure rise remain
fixed. The model has zero structural degrees of freedom.

At 12.7558356 kW, bottom-up initialization fails at the SGHP and a direct solve
using the converged relaxed snapshot as starting values reports local
infeasibility. Its largest residual is a source-outlet enthalpy connection of
323.20 J/kg (scaled 0.003232). The returned values are failed iterates.
That initial trial was explicitly marked failed.

`check_cycle_power.py` performs a separate control at **15.2000544283 kW**,
keeping all other selected specifications exact and leaving makeup flow free.
It converges with maximum scaled violation **6.26e-13**, steam/makeup
**70.34350427 kg/h**, and COP **4.59881485**. DM analysis finds no unmatched or
under/overconstrained sets. `cycle_power_control_result.json` and
`cycle_power_control_results.json` save that control check. The user subsequently selected 15.20 kW for the working demonstration.

The preceding flow-target diagnostic remains reproducible using preserved
`cycle_flow_target_information.json` and `cycle_flow_target_specification.json`.
The example-only `saved_state_guesses.py` shares snapshot guesses and native
property evaluation between these attempts; it changes no model equations or
fixity and is not a new library initialization algorithm.

## Current working cycle demonstration: 15.20 kW

The user selected fixed SGHP electrical power of **15.20 kW**, replacing the
fixed 55.99 kg/h makeup flow. `attempt_cycle.py` now defaults to that value,
represented by the explicit `attempt_sghp_operating_power` assumption in
`cycle_attempt_information.json` and `cycle_attempt_specification.json`.

The direct solve converges using the previously converged relaxed snapshot as
a starting guess: **70.3435064 kg/h** steam and makeup, COP **4.59882774**, source
heat extraction **54.7021817 kW**, hot-water duty **44.3033767 kW**, and warm-water
duty **25.5988049 kW**. Maximum scaled violation is **6.27e-13**.
`cycle_results.json` is now an optimal snapshot for this fixed-power case, not
a relaxed-specification diagnostic. Bottom-up initialization still fails at
the SGHP, so the example retains its documented saved-state fallback.

At the lower 12.7558356 kW power, the same source duty would require COP
1 + 54.7021817/12.7558356 = **5.2884044**. The failed solve left a source-side
enthalpy connection residual, not a zero-steam result. This is evidence of a
conflict among the retained heat-input, compressor and exchanger conditions on
the attempted branch; it is not proof of a universal minimum compressor power.

### Open a complete case in the viewer

In the viewer's **Model controls & help**, use **Open workspace** to load one file.
The checked-in/generated `workspace.json` bundles the aggregate snapshot from
`results.json` and `attempt_information.json`; `cycle_workspace.json` bundles
`cycle_results.json` and `cycle_attempt_information.json`. These preserve the
snapshots' original run identity, solve status and specification metadata.

Regenerate from saved files without solving again:

```bash
.venv/bin/python examples/steam_generating_heat_pump_system/export_workspace.py
.venv/bin/python examples/steam_generating_heat_pump_system/export_workspace.py \
  --results cycle_results.json --information cycle_attempt_information.json \
  --output cycle_workspace.json
```

The script accepts any saved results/information pair (relative paths are resolved
against this directory). Use information from the same case, including overrides.

`attempt_bottom_up.py`, `attempt_cycle.py`, `check_cycle_power.py`, and the cycle
specification-relaxation diagnostic now write workspace files alongside their
existing result snapshots. Aggregate power comparisons also export a workspace
for each case using their actual modified records. `replay.py` writes
`replay_workspace.json` and, with `--with-flash`, `flash_replay_workspace.json`.
`build.py` writes `<sghp>_<phnix>_workspace.json` marked **not_solved**, since it only
constructs a model. These exports do not turn failed or diagnostic runs into solved
cases.

Workspaces include only choices, information records and a results snapshot. Model
definitions must already be present in the viewer; layouts and navigation are not
part of the file. The results snapshot's existing model ID selects the root.

## Aggregate/aggregate comparison at fixed 15.20 kW

Run `OPENBLAS_NUM_THREADS=1 .venv/bin/python examples/steam_generating_heat_pump_system/compare_aggregate_power.py`.
This keeps the aggregate PHNIX and all shared operating conditions, releases
makeup flow, and attempts to fix SGHP power at 15.20 kW. The original operating
documents and cycle results are not changed.

Unlike the cycle case, the aggregate specification swap is rejected by
`pair_specification`: no structurally admissible replacement exists. The script
records that rejection, applies only the admissible partial specification, and
then manually fixes power solely to diagnose the rejected equation system. These
are explicitly diagnostic results, not accepted simulation specifications.
Although simple equation counting gives zero DOF, actual DM analysis finds one
unmatched variable and one unmatched equation (under/overconstrained parts).
The scaled Jacobian has rank 956 of 957.

With the existing COP **4**, SGHP source duty is `(4-1)*15.20 = 45.60 kW`.
The retained PHNIX, source temperatures, adiabatic tank and pump conditions
require **54.70218 kW**. IPOPT reports local infeasibility. This cannot provide a
meaningful steam comparison with the cycle case.

Setting aggregate COP to the cycle's **4.5988277408** makes the source and total
heating duties agree (**54.70218 kW** source, **69.90218 kW** heating). However,
the same structural deficiency remains: aggregate heat allocation between the
hot and warm circuits is free. Two different starting guesses reached feasible
points with steam rates **63.9712** and **56.8878 kg/h**, respectively, despite
identical selected numerical values. The second also has about 55.35% vapor in
the warm outlet, so it is not the intended liquid warm-water operating regime.
Both diagnostic snapshots are labelled `feasible`, not valid optimal simulation
predictions; the reports have `accepted_specification=false` and `solved=false`.
This demonstrates why a solver's optimal termination alone is insufficient.

A well-posed fixed-power aggregate comparison needs a heat-allocation condition
(e.g. warm-water duty or outlet temperature), and should release the aggregate
COP so the source-loop energy balance determines it under the retained PHNIX
input. Calibrating both COP and heat allocation from the cycle would check
energy/water-loop consistency rather than independently validate its performance.
Choosing that additional operating closure has been left for discussion.

`aggregate_power_comparison.json` contains all three diagnostic attempts,
with individual information/specification/report/results artifacts under
`aggregate_power_*`. The saved specification files deliberately contain only
the admissible partial fixes when the complete pattern is rejected; the extra
manual power fixation and its rejection are recorded in each report.

## Current common operating specifications for both fidelities

Run from the repository root:

```sh
OPENBLAS_NUM_THREADS=1 .venv/bin/python examples/steam_generating_heat_pump_system/compare_fidelities.py
```

PHNIX remains aggregate in both cases. All shared operating records are
identical, including SGHP power **15.20 kW**, warm-water duty
**25.5988049126 kW**, PHNIX power/COP, water inlet temperatures, pressures and
flows, and flash outlet qualities. The warm duty is an explicit comparison
assumption frozen from the previous successful cycle case. Makeup/steam flow
and SGHP COP are free predictions in both cases. Compressor pressure rise is
also free in the cycle, replacing the previous fixed captured pressure rise
with the warm-duty condition. Only the detailed cycle additionally uses its
four captured exchanger conductances and compressor efficiency.

Both specifications pass the normal canonical replacement validation and DM
checks with no unmatched or under/overconstrained sets. Both are square and
numerically full rank: **957/957** aggregate and **1750/1750** cycle. Both
IPOPT solves terminate optimal, with maximum scaled violations **4.75e-11**
and **2.01e-11**, respectively. No equations are removed and no specifications
are relaxed. The saved cycle state is used only as a starting guess.

| Quantity | Aggregate SGHP | Cycle SGHP |
| --- | ---: | ---: |
| Steam and makeup | 70.3435064 kg/h | 70.3435064 kg/h |
| SGHP COP | 4.59882774 | 4.59882774 |
| Total heating | 69.9021817 kW | 69.9021817 kW |
| Hot-water duty | 44.3033767 kW | 44.3033767 kW |
| Warm-water duty (specified) | 25.5988049 kW | 25.5988049 kW |
| Source heat extraction | 54.7021817 kW | 54.7021817 kW |
| Source circulation | 8.06371788 kg/s | 8.06371788 kg/s |

All reported shared water-side properties agree to numerical tolerance
(largest absolute reported difference about 2.03e-8 J/kg). Both warm-water
outlets are liquid. The detailed cycle predicts compressor pressure rise
**2.10569447 MPa** on this solution branch.

This establishes consistency for a common operating case, rather than
independent agreement of performance predictions: the source balance and fixed
electrical power determine aggregate COP, and the specified heat allocation was
taken from the cycle reference. The detailed cycle still enforces refrigerant
properties, exchanger laws and compressor physics absent from the aggregate.

`common_operating_information.json` contains the shared information. Each
`common_aggregate_aggregate_*` / `common_cycle_aggregate_*` group contains its
accepted specification, report, results snapshot and single-file workspace.
Load the corresponding `_workspace.json` in the viewer to inspect that case.
`common_fidelity_comparison.json` records the pairwise differences. Existing
historical operating files remain available unchanged.

## Aggregate thermal dynamics: PHNIX power step

The user-selected first dynamic demonstration holds both heat-pump COPs and
electrical powers constant except for the PHNIX input step. It represents
distributed source-, warm- and hot-water storage as three well-mixed liquid
inventories, each initially **100 litres**, at prescribed pressures. These
illustrative inventories are not claims about three additional physical plant
tanks or measured plant volumes. Flash separation, pumps, heat exchangers and
heat-pump performance remain algebraic; pressure/flash-vessel dynamics and
controllers are not included.

```sh
# 60 s backward-Euler grid, 600 s run, +10% PHNIX power after t=120 s
OPENBLAS_NUM_THREADS=1 .venv/bin/python examples/steam_generating_heat_pump_system/run_thermal_dynamics.py
# Constant-input equilibrium check
OPENBLAS_NUM_THREADS=1 .venv/bin/python examples/steam_generating_heat_pump_system/run_thermal_dynamics.py --step-fraction 0 --prefix thermal_no_step
# 30 s refinement
OPENBLAS_NUM_THREADS=1 .venv/bin/python examples/steam_generating_heat_pump_system/run_thermal_dynamics.py --nfe 20 --prefix thermal_step_refined
# Independently check balances, compare grids, write CSV and figure
MPLCONFIGDIR=/tmp/multifidelity-matplotlib .venv/bin/python examples/steam_generating_heat_pump_system/verify_thermal_dynamics.py
```

The separate `steam_generating_heat_pump_system_thermal` definition preserves
the steady plant example. It replaces the source conditioner with the existing
PH-stream tank model, inserts warm/hot inventories immediately before the SGHP
inlets, and removes the source mass-recycle cut: the dynamic tank mass balance
now closes that loop. All three tanks conserve mass and internal energy using
Helmholtz water density and `U = m h - P V`. Their initial masses and energies
come from the converged common aggregate case; only the initial time slice is
fixed. Area is 1 m², giving an initial level of 0.1 m. Volume/level may change
with density and mass; 100 litres is the initial water inventory, not a fixed
volume imposed throughout the transient.

The former source- and warm-loop temperature specifications become initial
conditions, not temperature controllers. Circulation withdrawals, warm splitter
fraction and makeup flow are held at their steady values. Tank pressures are
fixed at source/warm **2 bar absolute**, hot **4 bar absolute**; source and warm
valve pressure drops retain their steady values. External PHNIX source, makeup
and cooling-water boundary temperatures retain their original specifications.
SGHP COP is **4.59882774**, power **15.20 kW**, warm-water duty **25.5988049 kW**;
PHNIX COP is **2**. Dynamic initial conditions are six mass/energy records; no
loop temperature is fixed across time.

PHNIX electrical power changes **27.3281 -> 30.0609 kW** at 120 s. With the
backward-Euler interval convention, the changed input is recorded at the first
sample strictly after 120 s, representing the interval immediately after the
step boundary. This avoids accidentally applying the new power over the
preceding interval.

| Quantity | At 0 s | At 600 s |
| --- | ---: | ---: |
| Source inventory temperature | 75.38367°C | 81.80015°C |
| Warm inventory temperature | 59.48463°C | 59.48463°C |
| Hot inventory temperature | 124.76141°C | 124.76141°C |
| Steam | 70.34351 kg/h | 70.34351 kg/h |

The extra PHNIX heat accumulates in the source loop: approximately **2.62355 MJ**
over the 480 seconds after the step. Fixed SGHP COP and power keep its source
extraction and heating duties constant, so warm/hot temperatures and steam
production remain effectively unchanged. This thermal ramp is expected; the
model has no temperature-dependent performance feedback to establish a new
source-loop steady state. A detailed cycle or temperature-dependent aggregate
COP would allow changing source temperature to affect SGHP duty.

All three runs solve with zero DOF, no unmatched or under/overconstrained DM
sets, and negligible scaled residuals. The no-step temperature drift is below
**3e-12 K**. Coarse/refined temperatures differ by at most **6.9e-6 K**.
Independent plant-boundary integrations agree with inventory changes within
**3e-14 kg** per interval and **3e-8 J** over the run. These checks use makeup/steam
mass fluxes, PHNIX sink heat, SGHP electrical power, pump power, cooling duty
and makeup/steam enthalpy fluxes, rather than only rechecking tank equations.
`tests/test_sghp_thermal_dynamics.py` also verifies initial-only fixity, step
timing, thermal accumulation and the expected unchanged downstream response.

Open **`thermal_step_workspace.json`** in the viewer for the new model,
information, selected initial/operating specifications and time-series results.
`thermal_step.csv` provides a compact trajectory; `thermal_response.png` shows
the response. `thermal_verification.json` records the no-step, conservation and
refinement checks. Corresponding `_no_step` and `_refined` artifacts preserve
the other runs.

## Detailed SGHP dynamic relationship

The same `steam_generating_heat_pump_system_thermal` model can select the
SGHP `cycle` relationship using `thermal_cycle.json`. Only the SGHP selection
subtree differs from `thermal_aggregate.json`; PHNIX stays aggregate and all
water inventories, topology, flow settings, initial states, pressures, powers,
warm duty and PHNIX power-step settings are retained.

```sh
# Default: 60 s grid, SGHP cycle; output prefix thermal_cycle_step
OPENBLAS_NUM_THREADS=1 .venv/bin/python examples/steam_generating_heat_pump_system/run_thermal_dynamics.py --sghp cycle
# 30 s grid
OPENBLAS_NUM_THREADS=1 .venv/bin/python examples/steam_generating_heat_pump_system/run_thermal_dynamics.py --sghp cycle --nfe 20 --prefix thermal_cycle_step_refined
# Detailed no-step equilibrium check
OPENBLAS_NUM_THREADS=1 .venv/bin/python examples/steam_generating_heat_pump_system/run_thermal_dynamics.py --sghp cycle --step-fraction 0 --prefix thermal_cycle_no_step
MPLCONFIGDIR=/tmp/multifidelity-matplotlib .venv/bin/python examples/steam_generating_heat_pump_system/verify_cycle_dynamics.py
```

The cycle calculates COP, so the aggregate's fixed COP has no input counterpart.
A first structural check found one unmatched variable per time point. The user
selected fixed compressor pressure rise at the matching steady value,
**2.1056944726 MPa**, to replace that operating choice. The runner selects this
value from `common_cycle_aggregate_results.json` by default; `--pressure-rise`
can supply an explicit pressure rise in Pa. Four captured exchanger
conductances and compressor efficiency retain their existing cycle values.
This is an algebraic refrigerant cycle coupled to dynamic water inventories;
no refrigerant charge, compressor inertia or pressure-controller dynamics are
introduced.

All detailed cases pass the standard specification pairing and unit checks,
with zero DOF and no unmatched or under/overconstrained DM sets. No
specifications are relaxed. The no-step run holds its initial equilibrium,
with temperature drift below **4e-12 K**. The step case's largest scaled
violation is approximately **7.1e-11** on the 60 s grid.

At 600 s, the detailed results are:

| Quantity | 60 s grid | 30 s grid | Aggregate |
| --- | ---: | ---: | ---: |
| Source temperature | 79.20868°C | 79.27541°C | 81.80015°C |
| SGHP COP | 4.822734 | 4.826610 | 4.598828 |
| Steam production | 76.01538 kg/h | 76.11355 kg/h | 70.34351 kg/h |

Unlike fixed-COP aggregate performance, the cycle extracts more source heat
as the source warms. At fixed 15.20 kW compressor power, its COP and hot-water
heating duty increase, raising steam production and reducing source-water
heat accumulation. Warm-water duty remains prescribed; the warm-loop
temperature stays near 59.48463°C and the hot-loop temperature changes by
only about 0.0012 K.

The source-loop mass remains constant. Hot-loop mass falls by approximately
**0.49 kg** on the 60 s grid (**0.48 kg** on the 30 s grid), since makeup stays
fixed at the original 70.34351 kg/h while steam export increases. This is
conserved withdrawal from inventory, not an unnoticed additional water feed
or a fixed tank mass. No level controller is included. Compressor inlet
vapor fraction remains 1 and all tank levels remain positive.

Independent plant-boundary mass and energy integrations close to approximately
**2e-14 kg** per interval and **3e-8 J** over each run. The maximum difference
between the 60 s and 30 s temperature trajectories is **0.06674 K**, and steam
rates differ by at most **0.09818 kg/h**. The stated precision of the trajectory
is limited by this time-grid comparison and the illustrative water volumes.
The numerical regression tests cover both fidelity selections, initial-only
inventory fixity, varying COP/steam and the hot-inventory mass deficit.

Open `thermal_cycle_step_refined_workspace.json` for the finer detailed run,
or `thermal_cycle_step_workspace.json` for the 60 s run.
`thermal_cycle_comparison.png` compares aggregate and cycle trajectories;
`thermal_cycle_step.csv` contains the 60 s detailed trajectory.
`thermal_cycle_verification.json` records conservation, no-step, refinement
and phase/level checks.
