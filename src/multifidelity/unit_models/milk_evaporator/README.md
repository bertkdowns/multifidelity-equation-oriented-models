# Milk evaporator

`MilkEvaporator` provides one milk feed, one milk product, and one pure-water
steam/condensate outlet. Positive `mvr_power[t]` is shaft work entering the
effect; electrical consumption equals this only under an ideal-motor assumption.
The effect is steady state, with no ambient heat loss or holdup.

The default formulations are `low: AggregateMilkEvaporator()` and
`high: DetailedMilkEvaporator()`. Builders receive the parent model directly.
`select_fidelity()` changes activation only, preserving values and fixation
flags. It does not calibrate parameters, alter specifications, or solve.

## Public interface and specifications

Supply `milk_property_package` and `water_property_package`. The supported
example uses Ahuora's water/milk-solid thermodynamics with an FPhx state
definition (`multifidelity.property_models.milk.milk_parameters`) and Ahuora's
pure-water PH Helmholtz package. Changing the milk state definition preserves
the published thermodynamic equations while making enthalpy directly specifiable.

| Quantity | Normal role |
| --- | --- |
| `milk_inlet` | Specify molar flow, mole fractions, molar enthalpy and pressure, or connect upstream |
| `milk_outlet` | Calculated flow, composition, molar enthalpy and pressure |
| `water_outlet` | Calculated flow, molar enthalpy and pressure; may be two-phase |
| `mvr_power[t]` | Specify positive MVR shaft power, W |
| `operating_pressure[t]` | Specify milk evaporation/separator pressure, Pa |
| `heat_duty[t]` | Calculated internal heat transfer to milk, W |
| `recompressed_enthalpy[t]` | Calculated recompressed-stream molar enthalpy, J/mol |
| `heat_recovery_effectiveness[t]` | Specify effectiveness in [0,1] in both fidelities, relative to a saturated-liquid discharge reference |
| `water_removal_rate[t]` | Calculated pure-water outlet mass flow, kg/s |
| `product_solids_mass_fraction[t]` | Calculated overall product solids mass fraction |
| `energy_residual[t]` | Inlet enthalpy flow + work − external outlet enthalpy flows, W |
| `component_residual[t,j]` | Inlet − external outlet component molar flows, mol/s |

Temperatures and phase fractions are accessible on the three `*_state[t]`
blocks. They follow the property equations, not separate temperature targets.
For two-phase water, pressure and temperature alone do not define the outlet
energy. Normal operation has positive feed flow and water removal; zero-flow
and shutdown modes are outside this initial model's domain.

## Detailed formulation

The internal topology matches an effect in Ahuora's
**SGHP Milk Effect (BOIPOPT paper)**, captured revision 20:

```text
milk inlet → valve → HX cold side → separator → milk outlet
                                      ↓ vapor-rich branch
                                 translator → MVR → HX hot side → water outlet
```

The implementation uses `ahuora-builder`'s `ValveWrapper`,
`CustomHeatExchanger`, `CustomSeparator`, `GenericTranslator`, and `Compressor`.
The valve is adiabatic letdown without a hydraulic coefficient law. The exchanger
uses its lumped LMTD formulation; "high" here describes the complete effect's
internal equipment structure, not a spatially resolved exchanger.

Specify `high.heat_exchanger.overall_heat_transfer_coefficient` and
`high.mvr.efficiency_isentropic`. The builder fixes exchanger pressure drops to
zero and phase recoveries to the captured numerical 99% liquid-to-product and
1% vapor-to-product values. These recoveries can be changed explicitly on the
separator. Exchanger area, MVR discharge pressure and product concentration are
calculated. Area remains free: the exchanger heat-transfer equation and the
shared effectiveness target determine the required design area.

The translator preserves retained water molar flow, pressure, and molar enthalpy,
dropping carried milk solids. It is deliberately the published translator rather
than an energy-conserving replacement. The separator uses its original
equal-temperature split. Consequently detailed overall balance residuals can be
small but nonzero. `high.ignored_solids_flow[t]`,
`high.translator_energy_loss[t]`, and `high.separator_energy_residual[t]`
make these discrepancies explicit. The redundant water-composition equality
between the two normalized product outlet states is omitted; solids equality
and normalization still impose identical water composition.

## Aggregate formulation

There are no internal equipment models. Water and milk solids are conserved
exactly, as is total energy:

```text
H_feed + W = H_product + H_water
P_product = P_operating
```

The caller fixes the shared `heat_recovery_effectiveness[t]` variable in [0,1]
and supplies affine correlation parameters
for product molar enthalpy and water outlet pressure. Their inputs are deviations
in feed molar enthalpy, specific shaft work `W / feed.flow_mol`, operating pressure,
and effectiveness from declared reference values. Coefficient units are explicit.
Reference values and all slopes are mutable parameters on the low block. Default
values are starting assumptions, not universally valid equipment correlations.
Feed composition enters the component balances and thermodynamic calculations.

Let `n` be the outgoing water molar flow, `h_v` saturated pure-water vapor
enthalpy at operating pressure, `h_r` recompressed enthalpy, and `h_l` saturated
liquid enthalpy at water-outlet pressure. The remaining closures are:

```text
n (h_r - h_v) = W
Q = effectiveness * n (h_r - h_l)
n h_water = n h_r - Q
```

This replaces explicit translation, compression and heat exchange with a
saturated-vapor source approximation, work balance, and recovery relation. It
does not imply `Q = effectiveness * W`; recovered latent heat can make Q much
larger than W. Water outlet enthalpy follows these balances and is not constrained
by another correlation. Parameter combinations must produce physically admissible
flows and states within the property packages' domains.

Both formulations use the same parent-owned effectiveness variable and recovery
equation. The normal public specifications are feed, power, operating pressure,
and effectiveness. These variables have initial guesses but are not automatically
fixed by construction; the caller fixes them or supplies flowsheet constraints.
For example, `effect.heat_recovery_effectiveness.fix(0.75)` applies to both
fidelities. The former private `low.effectiveness` parameter has been removed.
Choosing equipment parameters versus aggregate correlations is explicit caller
work, not part of selecting a formulation. Identical specifications do not
guarantee feasibility in both models; selection never changes the target to
obtain a solution.

## Initialization and example

`initialize(solver=...)` temporarily fixes the current feed state, invokes the
existing milk-property initialization routines, and solves the selected effect.
Caller-provided internal guesses are used for the detailed representation.
Variable fixation flags are restored on success or failure; failed solves can
change values. External flowsheet constraints still require a complete flowsheet
solve. This is not a new recycle-initialization algorithm.

See `case_studies/milk_evaporator/example.py` and its README for a reproducible
single-effect comparison. IPOPT and IDAES Helmholtz extensions are required.
