# Steam-generating heat-pump demonstration plant

This example constructs one physical plant with independently selectable
representations for its steam-generating heat pump (`sghp`) and PHNIX source-water
heat pump (`phnix`). Switching either heat pump leaves the plant connections and
public variable paths unchanged.

The process reference is the [SGHP thesis note](https://bertkdowns.github.io/thesis/notes/2ic55zb4xauos9xnvjtny5l/)
and the [as-built P&ID V22, 27 July 2026](https://bertkdowns.github.io/thesis/assets/SGHP%20P%26ID%20V22.pdf),
linked from its commissioning notes. The requested platform comparison is
[Ahuora SGHP-DT](https://ahuoratech.app/project/2384/flowsheet).

## Build four representations of the same plant

Run from the repository root:

```bash
.venv/bin/python examples/steam_generating_heat_pump_system/build.py
.venv/bin/python examples/steam_generating_heat_pump_system/build.py --sghp cycle
.venv/bin/python examples/steam_generating_heat_pump_system/build.py --phnix cycle
.venv/bin/python examples/steam_generating_heat_pump_system/build.py --sghp cycle --phnix cycle
```

Each command loads an explicit implementation document, constructs equations,
checks unit consistency, and prints the required input families. It does not fix
values, initialize, or solve. The filenames list SGHP choice first, PHNIX second.
The same implementation documents work with the existing CLI:

```bash
.venv/bin/python -m multifidelity.model_language steam_generating_heat_pump_system \
  examples/steam_generating_heat_pump_system/aggregate_aggregate.json --required-inputs
```

## Equipment boundaries and loops

`steam_generating_heat_pump_system.json` owns the following main process paths:

| Circuit | Main process path |
| --- | --- |
| Source water | SGHP evaporator outlet → source valve/line loss → source pump → holdup tank → PHNIX sink side → electric heater → SGHP evaporator inlet |
| Warm water | Makeup mixer → pipe pressure loss → warm-water pump → SGHP subcooler → splitter → cooling exchanger → makeup mixer |
| Hot water | Flash liquid → hot-water pump → mixer with warm makeup (through its own valve) → SGHP condenser → flash valve → flash tank |
| Steam | Flash vapor → steam valve → exported steam |

The PHNIX source inlet/outlet and cooling-exchanger cooling-water inlet/outlet
are exposed at the system boundary. The PHNIX source names deliberately do not
assume an ambient-air or water-network implementation: the normal `heat_pump`
stream interface is used, with illustrative water-property bindings in the
shipped selections. The platform also calls this stream “Air Source” while assigning
water as its compound. This retains the reference modelling assumption; it is not
a validated air-source property representation.

The `steam_generating_heat_pump_unit` definition provides six public water
streams: `source_inlet/outlet`, `warm_inlet/outlet`, and `hot_inlet/outlet`.
Its aggregate alternative uses prescribed COP and electrical power, plus a
separately supplied warm-water heating duty. The total heating duty is
`COP * electrical_power`; condenser duty is total heating minus warm-water
subcooler duty, and source cooling is total heating minus electrical power.
Thus subcooler heat is included once in the aggregate heating COP. A COP measured
using condenser duty alone must be converted to this convention before use.

The cycle alternative uses the compressor, condenser, subcooler, IHX, expansion
valve, and evaporator definitions already used by the existing SGHP scaffold.
PHNIX uses the normal `heat_pump` definition with its own aggregate/cycle choice.
Both heat pumps report electrical power and COP at stable public paths.

The older `steam_generating_heat_pump` definition is retained. It includes the
flash tank and water-loop equipment inside its detailed relationship, while its
aggregate alternative exposes only makeup and steam. That boundary cannot serve
as an interchangeable three-circuit unit inside this plant. The new unit reuses
its equipment definitions with the water circuits exposed; the system owns the
surrounding loops and flash tank in every representation. Both definitions are
retained for now by agreement. Consolidating the overlapping definitions and
making the model hierarchy easier to read is deferred cleanup.

## Values, information records, and future plant data

The reference was inspected through the Ahuora MCP on 4 November 2026 (NZDT),
content revision 2. Its captured configuration is recorded in
[`ahuora_reference.json`](ahuora_reference.json), with values, display text,
formulas, structural replacements, original units, ports, and tags. These are
current stored values, **not immutable SolveRun results or live plant readings**.

- [`information.json`](information.json): 25 applicable configuration records,
  including PHNIX power/COP, heater duty, pump settings, UA values and boundary conditions.
- [`reference_observations.json`](reference_observations.json): 100 captured or
  derived comparison records, kept separate from the configuration. They use
  the `assumption` type, not `sensor_reading`; copying a platform output does not
  turn it into measured evidence.
- [`value_provenance.json`](value_provenance.json): exact source property-value
  identities and transformation notes for every information/replay record.
- [`reference_checks.json`](reference_checks.json): stored-value differences at
  the manual return cuts and the zero-steam state.

Actual tags are retained where present. Untagged records use the explicit
`ahuora.property_value.<id>` namespace, not invented PLC tags. Uncertainty is
unknown and left unspecified. Trust ranks are local priority judgments, not
probabilities or sensor quality assessments. The records retain mass-flow and
mass-enthalpy units directly (`kg/h`, `t/h`, `kg/min`, `kJ/kg`); application
converts them into the model's SI units without guessing molar enthalpy bases.

| Reference setting | Copied value |
| --- | --- |
| PHNIX work / heating COP | 25 kW / 2 |
| Source electric heater | 200 W (`SOEH31`) |
| SGHP compressor isentropic efficiency | 0.75 |
| Source / warm-water / hot-water pump efficiencies | 0.9 / 0.9 / 1 |
| Condenser / evaporator / subcooler / IHX UA | 30,000 / 5,000 / 400 / 5 W/K |
| Cooling-exchanger UA | 540 W/K |
| Warm-water pump work | 6 W, from the platform VSD formula |
| Flash pressure | 200 kPa |

The PHNIX COP is a structural replacement setpoint: Carnot efficiency is the
manipulated variable. Likewise, the SGHP compressor work is manipulated to meet
a discharge-pressure specification; its captured 2.37573 kW must not be mistaken
for an independent configured 6 kW simply because that display text is retained.
An `enabled` flag alone does not identify a fixed specification. The transcription
uses captured numeric `value`, retaining `displayValue` separately for audit; it
does not interpret arbitrary formula strings as executable local expressions.

To select and apply the applicable configuration for a representation:

```bash
.venv/bin/python examples/steam_generating_heat_pump_system/build.py --sghp cycle --apply-reference
```

This reserves steam flow and total power for prediction, returns per-record
selection decisions, and applies only the partial structural specification.
Unavailable relationship-specific records are reported. The supplied configuration
is insufficient to specify any of the four full-plant representations; the command
does not invent closure values or attempt an underdetermined numerical solve.
Captured comparison outputs are not passed to this selector automatically.

## Numerical replay of the aggregate SGHP unit

```bash
.venv/bin/python examples/steam_generating_heat_pump_system/replay.py
```

Requires IPOPT. This builds just the three-circuit aggregate SGHP unit using
[`sghp_replay_information.json`](sghp_replay_information.json) and
[`sghp_replay_specification.json`](sghp_replay_specification.json). It fixes the
three inlet PH/flow states, captured compressor work, captured warm-water duty,
and a COP calibrated at that same point. All outlet variables remain free.

The captured condenser and subcooler duties are 30.7446756 and 12.2512681 kW,
with compressor work 2.3757297 kW. Their ratio gives total heating COP 18.097995.
The replay solves and reproduces the three captured outlet enthalpies:

| Outlet | Specific enthalpy |
| --- | --- |
| Source water | 340.3464717 kJ/kg |
| Hot water | 355.2798995 kJ/kg |
| Warm water | 171.4533185 kJ/kg |

This is a value-mapping and balance replay, not independent validation of COP,
prediction accuracy, electrical efficiency, or actual steam production. The
compressor mechanical work is treated as electrical power without motor losses.

## Differences from the platform reference

The full local plant closes loops that are manually separated in the platform.
The captured hot-water mixer outlet (`ManualRecycle`) has flow 1.6027031 kg/s,
while the independent condenser inlet (`M`) has 1.5349008 kg/s. The source-pump
outlet and independent PHNIX sink inlet differ by about 9.5942 kW in energy flow.
The configured warm-water split implies a return of 0.2385802 kg/s, while the
captured cooling-exchanger inlet has 0.1500085 kg/s. These are differences between
stored values; they are not attributed to a successful immutable solve or used
to claim a platform modelling failure.

Captured steam flow is zero. The flash inlet/condensate is subcooled at about
84.8 °C and 200 kPa. Its saved liquid/vapor enthalpies are **not a consistent pair
of saturated outlet enthalpies** for the local equilibrium-flash approximation,
so they are comparison records, not automatic flash-parameter specifications.
A steam-producing full-plant point still needs to be selected and reconciled.

The platform's hot-water pump precedes the makeup mixer, its warm-water pipe
loss precedes the warm-water pump, and the source heater follows PHNIX. The local
main-path ordering now follows those inspected connections. The P&ID holdup tank
and steam valve remain explicit local elements, although they have no direct
counterparts in the platform snapshot; no platform values are invented for them.
Receivers/accumulators are lumped out of the local cycle. The platform IHX labels
its vapor side `hot` and liquid side `cold`; the existing local cycle uses the
opposite side naming. Internal snapshot values therefore cannot be copied by
matching side names alone.

Useful stable paths for future information records and outputs include:

- `sghp.source_inlet.enthalpy`, `sghp.hot_outlet.enthalpy`, and `sghp.warm_outlet.enthalpy`;
- `sghp.performance.electrical_power` and `phnix.performance.electrical_power`;
- `source_pump.outlet.flow`, `warm_water_pump.outlet.flow`, and `hot_water_pump.outlet.flow`;
- `flash_tank.inlet.pressure` and `steam_outlet.flow`;
- `performance.electrical_power` for the two heat pumps, three pumps, and ideal electric source heater combined.

Public stream paths survive heat-pump representation changes. Internal
specification paths, such as `sghp.cop_model.parameters.cop`, exist only when
that relationship is selected. Sensor temperature records require explicit
property-state models exposing the relevant temperature or an upstream conversion
with recorded property assumptions; the plant stream interface itself uses PH.
No live connector, timestamp alignment, or automatic physical tag mapping is added.

## Scope of this first demonstration

This demonstrates deriving four equation systems from one plant definition.
The current cycle equations and water-surrogate refrigerant properties are
illustrative; selecting a cycle does not establish greater predictive accuracy
or reproduce the real butane circuit. PHNIX's actual internal topology is not
asserted by reusing the generic cycle model.

`water_flash.enthalpy_balance` conserves mass and energy with distinct liquid
and vapor enthalpies. Supply consistent saturated-water enthalpies at its inlet
pressure to use it as an equilibrium water flash. It does not calculate those
enthalpies itself. The old `flash_separator.split` assigns the inlet enthalpy to
both products and is unsuitable for representing steam generation here.

The source holdup tank currently uses `thermal_conditioner.energy_balance` as
a steady flow-through heat-loss element. It has no inventory or thermal dynamics.
This plant therefore does not yet represent startup, shutdown, or PLC response.
Bypass branches, relief devices, detailed valve characteristics, pressure losses
in exchangers, refrigerant receivers/accumulators and oil separation are omitted
or lumped. The electric heater's duty is counted as electrical power at unit
efficiency; cooling-water infrastructure and PHNIX auxiliaries are outside the
reported power boundary. A physically consistent steady operating point is still
needed: closed loops can have redundant balances or pressure constraints, and a
list from `required_inputs()` is not proof of independent specifications.
