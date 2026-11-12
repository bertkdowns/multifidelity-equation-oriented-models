# R600a ice maker

The two temperature logs support a lumped suction-temperature fit and a conditional thermodynamic cycle screen. The cycle screen exposes an inconsistency in treating all four refrigerant probes as bulk fluid temperatures at two shared pressures. Refrigerant charge and evaporator heat duty are unidentifiable from these logs alone.

## Logs and suction response

The 6 November export contains 2,161 one-second frames from logger AO012/780. The 10 November hot run contains 3,597 frames from logger B0004/550. Both are local dates in New Zealand. Channels 1–6 are suction, discharge, pre-capillary, post-capillary, ambient and evaporator water, respectively. Channels 0, 7 and 8 are unassigned. The water is the evaporator heat source. Temperatures are converted from °C to K for the fit.

The export has an isolated 89 °C suction spike at 5:06 elapsed with the other channels near room temperature. The hot run starts with erratic measurements and includes a −270 °C recorder value, treated as missing. The selected fit and validation windows lie in later, contiguous episodes. The model uses a 5 s grid interpolated from the actual logger timestamps. The shaded plot regions show the chosen windows. Validation starts from the measured suction temperature at the beginning of each window.

The model-library definition [suction_response.json](../../src/multifidelity/model_language/models/suction_response.json) fits the measured suction probe with a single time constant:

```text
τ dT_suction/dt = T_ambient + w (T_water − T_ambient) + b − T_suction
```

The water-only fit fixes the water weight `w` to 1. The combined fit estimates it between 0 and 1. The offset `b` absorbs unmeasured refrigeration and other heat flows. The time constant includes any lag in the measured probe response.

| Log | Model | Time constant (s) | Water weight | Offset (K) | Fit RMSE (°C) | Held-out RMSE (°C) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 6 Nov | Water only | 73.8 | 1.00 | −10.53 | 0.32 | 5.47 |
| 6 Nov | Water + ambient | 61.6 | 0.94 | −9.52 | 0.28 | 6.04 |
| 6 Nov | Hold the first suction value | | | | | 16.75 |
| 10 Nov | Water only | 112.2 | 1.00 | −6.73 | 0.49 | 0.75 |
| 10 Nov | Water + ambient | 62.3 | 0.41 | +2.00 | 0.15 | 0.55 |
| 10 Nov | Hold the first suction value | | | | | 0.53 |

The apparent water weight moves substantially between runs. The air term improves the hot-run fit and its held-out replay compared with water alone. It adds no demonstrated predictive skill over both baselines across the two logs. The fitted coefficients describe the selected episodes and cannot quantify an air-side or water-side UA. In a corresponding lumped energy balance, simultaneous scaling of the heat capacity, conductances and unmeasured heat duty leaves the temperature trajectory unchanged.

## R600a cycle and reported shaking

The larger discharge peak at **53:05 elapsed, 15:25:31.908 NZDT** is the closest identifiable marker to the description of shaking at the highest temperature. The log also has an earlier peak and lacks a vibration or compressor status channel, so the event timing remains approximate.

| Suction | Discharge | Pre-capillary | Post-capillary | Ambient | Evaporator water |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 29.75 °C | 92.64 °C | 76.50 °C | 68.78 °C | 21.81 °C | 34.14 °C |

At that peak the suction probe is 4.40 K cooler than the water and 7.94 K warmer than ambient. Heat entering the evaporator from water and heat leaving an exposed suction line to ambient could both occur. In the cooler export, the suction probe reaches −2.43 °C while ambient is 21.53 °C and water is 16.85 °C. Ambient air at that temperature would warm that cold section. Evaporator effectiveness needs heat duty and a driving temperature difference, ideally with water mass or flow and an evaporator-outlet refrigerant temperature.

The next level uses the native IDAES isobutane Helmholtz EOS for a four-state cycle. It assumes one pressure per side, vapour at compressor suction and discharge, liquid at the capillary inlet and isenthalpic expansion. Assigning 0–10 K suction superheat gives a **3.00–4.02 bar absolute** low-side scenario. Assigning 0–10 K pre-capillary subcooling gives a **12.50–15.32 bar absolute** high-side scenario. The 5 K / 5 K case gives 3.48 / 13.86 bar absolute and predicts approximately 41% vapour **by mass** at the capillary exit. The refrigerant mass flow is unknown, so the model gives only specific enthalpy changes. [Reference isobutane EOS](https://doi.org/10.1063/1.1901687)

That case predicts a **24.75 °C** flash temperature against the measured **68.78 °C**. Even the zero-superheat case is 39 K below the post-capillary reading. If the latter actually measured equilibrium two-phase refrigerant, it would imply **10.59 bar absolute** there. Reconciling that with equilibrium at the suction probe would require a large pressure drop or a different interpretation of at least one measurement. The cooler export also fails the shared-pressure test at its cold point, where the predicted capillary outlet is −7.43 °C and the observed probe reads 22.56 °C. Probe placement, tube-wall heat exchange, a local pressure drop and changing operating mode are candidates to distinguish with measurements.

If the shaking coincided with the peak and suction refrigerant was an equilibrated mixture at 29.75 °C, its saturation pressure was **4.02 bar absolute**. Shifting the assumed bulk temperature by ±3 K changes this to 3.69–4.37 bar absolute. This is a sensitivity calculation. The vibration is compatible with liquid return, and transient liquid carryover can occur even with warmer bulk suction vapour. [Copeland liquid refrigerant control bulletin](https://webapps.copeland.com/online-product-information/Publication/LaunchPDF?Index=AEB&PDF=1182)

### Possible hot-gas harvest transitions

The two main discharge-temperature maxima in each active run have similar spacing. The times are elapsed from the start of each file and use the highest raw reading in each peak cluster.

| Run | First discharge peak | Second discharge peak | Peak spacing |
| --- | --- | --- | --- |
| 6 Nov cooler run | 24:10.734 at 46.55 °C | 32:54.810 at 54.46 °C | 8 min 44.1 s |
| 10 Nov hot run | 44:30.005 at 86.26 °C | 53:05.080 at 92.64 °C | 8 min 35.1 s |

Around the second cooler peak, suction rises from −2.41 °C at 25 s before the peak to 17.77 °C at 15 s after. Around the second hot peak, discharge falls from 92.64 to 59.69 °C over 75 s while suction rises from 29.75 to 33.04 °C. Similar spacing and rapid changes are consistent with a recurring control transition. In harvest, a hot-gas valve can route discharge around the condenser and capillary into the evaporator. Liquid flooding can occur at the start or end of hot-gas defrost. The CSVs lack valve and vibration timestamps, so the peak times are candidate markers. The high post-capillary reading was already present before the second hot peak, and its persistence needs a separate explanation if the valve was closed then. [Sub-Zero harvest sequence](https://service.subzero.com/KnowledgeBase/DownloadExternal?an=19600001&id=158&isInternational=False), [Copeland liquid refrigerant control bulletin](https://webapps.copeland.com/online-product-information/Publication/LaunchPDF?Index=AEB&PDF=1182)

Treat freezing and hot-gas harvest as separate operating modes when evaluating the cycle. A model of harvest needs a discharge-to-evaporator bypass and transient refrigerant redistribution. Use a logged valve command or a synchronised harvest marker to identify the switch before fitting mode-specific parameters.

## Refrigerant holdup and steam

Use `m = V [(1 − f_liquid) ρ_vapour + f_liquid ρ_liquid]`, where `f_liquid` is the liquid **volume** fraction. At the 29.75 °C suction saturation scenario, each 100 mL contains **1.04 g** as vapour, **6.38 g** with 10% liquid by volume, or **54.46 g** filled with liquid.

### Hot-peak inventory with the 24 g charge

The revised case fixes the total charge to **24 g** and assumes **50 mL high-side volume** and **30 mL external low-side volume**. The compressor shell and oil together are a separate inventory, set to **5 g** in the reference case. The pressure scenario uses suction saturation at the logged 29.75 °C (**4.02 bar absolute**) and **15.6 bar absolute** discharge. Using saturated vapour for the gas compression step, this corresponds to about 60% isentropic efficiency at the logged discharge temperature. The implied condensing temperature is **87.39 °C**, about 10.9 K above the pre-capillary probe. The holdup calculation uses saturation densities on each side and assumes that 2% of the external low-side volume contains liquid.

With those assumptions, the mass balance assigns **0.63 g** to the external low side, **5.00 g** to the compressor and **18.37 g** to the high side. High-side liquid occupies **39.3 mL of the 50 mL**, or **79%**. The 2% assumption gives **0.60 mL of low-side liquid**. This describes a lumped inventory and leaves its distribution along the evaporator and suction line unknown.

| High-side volume | External low-side volume | External low-side liquid volume fraction | Compressor inventory | Required high-side liquid volume fraction |
| ---: | ---: | ---: | ---: | ---: |
| 50 mL | 30 mL | 2% | 0 g | Infeasible |
| 50 mL | 30 mL | 2% | 2 g | 93% |
| 50 mL | 30 mL | 2% | 5 g | 79% |
| 50 mL | 30 mL | 2% | 8 g | 64% |
| 35 mL | 30 mL | 2% | 5 g | Infeasible |
| 100 mL | 30 mL | 2% | 5 g | 34% |
| 50 mL | 15 mL | 2% | 5 g | 80% |
| 50 mL | 60 mL | 2% | 5 g | 76% |
| 50 mL | 30 mL | 10% | 5 g | 72% |

For a 5 g compressor inventory and 2% low-side liquid, the high side needs **at least 40 mL** even if filled with liquid at the assumed condensing temperature. At 35 mL, some of the remaining charge must be stored elsewhere or the assumed thermodynamic state must change. Conversely, the 24 g mass balance alone can accommodate an entirely liquid-filled 30 mL external low side. That would use 16.3 g there and leave just 2.7 g on the high side after the assumed 5 g in the compressor. This is a limiting redistribution scenario and does not describe steady vapour compression.

The pressure scenario still predicts a **29.75 °C** capillary flash, around **39 K** below the measured downstream probe. The calculated flash is **38% vapour by mass**, equivalent to about **3% liquid by volume** in a homogeneous equilibrium mixture at the capillary exit. The assumed 2% applies to the entire external low side and remains a separate input. The water is only **4.4 K** above the implied evaporation temperature. This gives a small positive driving temperature at the water probe. The model calculates specific evaporator and condenser duties of about **200 and 284 kJ/kg**. Heat duty in watts still requires refrigerant mass flow or a measured heat balance. These calculations test the implications of the assumed state and do not infer the event pressure or the amount of liquid that actually entered the compressor.

Atmospheric steam is a separate condenser design condition. Sustained boiling with a 5 K temperature approach requires about **105 °C condensing temperature and 21.78 bar absolute R600a saturation pressure**. At a 10 K approach it is **23.83 bar absolute**. The highest measured discharge temperature was 92.64 °C, and the logs contain no condenser-water temperature or steam flow. A steady steam duty and an operating point within the compressor envelope remain to be established. [Water phase-change data](https://webbook.nist.gov/cgi/cbook.cgi?ID=C7732185&Mask=4)

## Estimation in this framework

The runnable example builds the dynamic Pyomo model from JSON. It loads the observations through `InformationDocument`, fixes water, air and the initial suction state through `SpecificationDocument`, and adds a soft suction objective with an unweighted sum of squares. IPOPT estimates the free scalar parameters. For multiple comparable experiments, Pyomo 6.9.2 Parmest can fit shared parameters across independently initialized and labeled model instances. A trajectory belongs in one experiment block. A separate calibration plan can specify free parameter paths, hard inputs, soft observations, weights and fit/validation windows without changing the model definitions.

The dynamic inventory tier would reuse the framework's pipe holdup mass and energy balances, with pressure–enthalpy states, fixed geometry, independent wall heat capacities and a sealed total charge constraint. For fitting that tier, the most useful additional evidence is paired suction and discharge pressures, compressor status and event timing, nameplate charge and internal volumes, and a water-side heat balance. The [parameter estimation research note](../../research-ideas/ice-maker-parameter-estimation.md) describes the IDAES examples, pinned Parmest API and calibration design.

## Open in the model viewer

Use **Open workspace** in the viewer sidebar and select either of these files. The viewer selects the matching library model automatically.

- [workspace.json](workspace.json) opens **ice_maker_refrigeration_loop** at the hot discharge peak. Follow **compressor → condenser cooler → pre-capillary pipe → capillary valve → post-capillary pipe → evaporator heater → refrigerant mass recycle → compressor**. Both pipes use the pass-through relationship with state evaluation. Their ports show flow, pressure and enthalpy. Open each pipe's **state** child to see its R600a temperature and vapour fraction.
- The workspace information records specify the recycle flow and compressor efficiency directly on those units. The saved specification fixes compressor inlet and outlet pressures in place of the valve pressure drop and compressor pressure rise. It fixes the cooler and heater outlet enthalpies in place of their heat duties. The unit equations solve for those pressure changes and duties.
- In the cycle workspace, drill into the compressor for its inlet and outlet R600a states. The **Results** tab shows the calculated flash temperature and holdup. Probe temperatures appear as information overlays. The model uses a **1 kg/s reference flow** to evaluate the unit equations. Read the root **specific_duties** in J/kg for the case comparison. The machine's actual flow and power remain unknown.
- [suction_workspace.json](suction_workspace.json) opens **suction_response** with the hot-run water and ambient fit over 2105–2635 s. The measured suction series is in **Information**, and the fitted trajectory and parameters are in **Results**.

## Reproduce

Run from the repository root with IPOPT and IDAES Helmholtz extensions available. Matplotlib is only needed for the optional plot.

```bash
.venv/bin/python examples/ice_maker/analyse.py \
  '/home/bd65/Downloads/export (2).csv' \
  '/home/bd65/Downloads/IceMaker Hot until liquid slug.csv' \
  --plot examples/ice_maker/diagnostics.png \
  --workspace-dir examples/ice_maker
```

[Temperature traces and held-out fits](diagnostics.png)
