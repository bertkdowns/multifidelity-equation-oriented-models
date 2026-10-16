# SGHP source-loop results and conclusions

## Research outcome

The reduced source loop is a working case study for equation switching and
residual-triggered valve refinement. **These experiments do not demonstrate an
initialization-success benefit from staging.** Direct and staged solving both
succeeded for every tested feasible condition and starting point. Staging often
reduced total IPOPT iterations, but its extra solver invocation increased median
wall time in this small model.

Selective refinement retained the linear valve for two of the three feasible
operating cases and upgraded it for the higher-flow case. It avoided 16 of the
24 nonlinear upgrades that unconditional staging performed across the feasible
trials. This is evidence that the mechanism can distinguish these chosen cases,
not a demonstration of a generally reliable refinement criterion.

## Evidence and reconstruction

Ahuora's “SGHP with ihx - Flow Correlations” project contains the relevant valve
in its “Multi-steady state version.” Saved Run 24 (“Testing Without
Initialisation”) ended at the iteration limit. Its recorded source-valve inlet
and outlet pressures were 250.000 and 303.235 kPa, respectively, with the
opening at zero and a pressure-flow residual reported by Ahuora. Saved Run 27
succeeded, with a 128.354831 kPa valve pressure drop and opening 0.03330991835.
The targeted current configuration and immutable historical outputs are in
[data/ahuora_evidence.json](data/ahuora_evidence.json).

The local model retains the source valve, pump, prescribed evaporator duty,
PHNIX heater, and steady tank in a closed water circuit. It uses a fixed absolute
pressure anchor and omits one redundant continuity equation. The rest of the
SGHP, its time-series inputs, initialization procedure, and remote equation
scaling are not reconstructed. In particular, the nonlinear pressure-flow
constraint is normalized locally. The historical failed and successful runs
are observations rather than a controlled comparison of identical remote
configurations.

The nonlinear law uses the water-referenced liquid relation and equal-percentage
characteristic found in Ahuora source commit
`f1d95218ae53bf8f59f141f3d2a0cb259bd71b42`. This is the inspected local source
version, not independently verified metadata for the deployed historical server.
Its equations are consistent with the saved successful point. The older main
checkout contained a different molar-flow default and was not used as the
liquid-law reference. The source paths, display-to-SI coefficient conversion,
and adopted specifications are recorded in
[data/reference_case.json](data/reference_case.json).

At the reference operating case, the reconstructed Helmholtz/nonlinear solution
has opening **0.03331048013** and valve pressure drop
**128.354499113 kPa**. Its differences from Run 27 are
approximately 5.6e-7 in opening and 0.332 Pa in pressure drop. This checks the
local hydraulic reconstruction; it does not validate the omitted SGHP physics.
The calculated source heat input is 46.093782946 kW,
consistent with evaporator heat removal minus pump shaft work.

## Experiment design

The recorded baseline was generated on 2026-10-16 using Python
3.14.0, IDAES 2.8.0, Pyomo
6.9.2, and IPOPT 3.13.2. IPOPT tolerance was 1e-8 and the
iteration limit was 200 per stage.

The 96 independent trials combine:

- Two property formulations: constant-cp linear water and liquid IAPWS-95.
- Four operating cases: reference; 20% higher flow; a 250 kPa pressure anchor;
  and a 15% lower-flow control-range stress case.
- Four initial guesses: near-reference, reversed pressures, equal pressures,
  and wide-open valve. Each strategy starts from a fresh model with identical
  guesses and specifications. No unreported unit initialization solves are used.
- Three strategies: direct nonlinear; linear then nonlinear; and linear with
  refinement when the normalized nonlinear residual exceeds 1e-3.

Success checks include solver termination, mass/energy conservation, and
positive valve pressure drop. Direct and staged acceptance additionally requires
an active nonlinear formulation and nonlinear residual below 1e-6. Selective
acceptance may keep the linear formulation at residual below 1e-3; these
approximate results are not counted as detailed-model validations. The opening
error is evaluated against a separate detailed solution of the same operating
case. Full definitions and commands are in [README.md](README.md).

## Recorded results

The counts below include all operating cases. Iteration and wall-time medians
are over accepted trials only, and include both stages where applicable.
“Detailed validated” means the nonlinear block is active and passes its residual
and conservation checks.

| Properties | Strategy | Accepted / attempts | Detailed validated | Median total iterations | Median solve seconds |
| --- | --- | --- | --- | --- | --- |
| helmholtz | direct | 12 / 16 | 12 | 5.0 | 0.0485 |
| helmholtz | staged | 12 / 16 | 12 | 3.5 | 0.0601 |
| helmholtz | selective | 12 / 16 | 4 | 3.5 | 0.0337 |
| linear | direct | 12 / 16 | 12 | 5.5 | 0.0138 |
| linear | staged | 12 / 16 | 12 | 4.5 | 0.0250 |
| linear | selective | 12 / 16 | 4 | 3.5 | 0.0128 |

All three feasible operating cases succeeded from all four starts, for both
property formulations and all strategies. All starts of the lower-flow stress
case were rejected by every strategy. Thus the 12/16 acceptance rates reflect
the operating-case grid, not random estimates of solver reliability.

At the reference case, staging used 3 total iterations versus 3 directly with
linear properties, and 2 versus 3 with Helmholtz properties. At higher flow,
staging used 5 versus 4 directly for both property formulations. Aggregate
median iteration reductions therefore do not imply a benefit at every point.
Timing measurements are a single local sweep, include solver-launch overhead,
and are too short and sparsely repeated to support a general speed claim.

Selective refinement upgraded all four higher-flow starts for each property
formulation and retained the linear valve for the reference and lower-pressure
cases. The largest absolute opening error against the nonlinear reference was
**3.69e-06** (fraction of full opening). This small error is specific to
this loop and nominal point; the residual threshold is not an established bound
on engineering error or an objective-sensitive selection policy.

Changing property fidelity had a larger reference opening effect than retaining
the valve approximation: 0.032045482 with linear water versus
0.033310480 with Helmholtz water. This supports keeping property and
equipment fidelity as separate experimental choices, without establishing which
approximation dominates in other operating regions.

## Why the low-flow case fails

Equal-percentage opening uses f(u) = 100^(u-1), so u=0 still gives f=0.01.
It is not an ideal shutoff model. With the adopted pump power and other
specifications, the lower-flow target would require opening below zero.
A diagnostic solve relaxing the opening lower bound to -0.1 converged to
approximately **-0.0208901** with linear water and **-0.0196249** with Helmholtz
water. These unphysical solutions are excluded from the strategy statistics.

This is evidence of a control-range limitation in the reduced model, rather
than a failure that better initialization should necessarily cure. The nonlinear
valve residual alone can be small at a failed point while the flow target or
other equations remain unsatisfied; conservation and specification checks are
therefore part of the acceptance criteria.

## Conclusions and next research steps

1. **The switching architecture works for the connected hydraulic loop.** The
   linear and nonlinear valve formulations share physical variables, preserve
   specifications, and converge to the same detailed root when staging succeeds.
2. **The original initialization difficulty has not yet been reproduced.** Even
   the reversed-pressure start solves directly in the reduced, normalized model.
   This does not disprove the historical problem or establish its root cause.
3. **Staging is not automatically cheaper.** In this grid it changes iteration
   counts without improving feasible-case success, and pays for an extra solve.
4. **A residual trigger can avoid unnecessary upgrades here.** The nominal
   linear approximation is adequate in two cases and warrants correction at
   higher flow. Broader operating sweeps and engineering-output sensitivity are
   needed before treating the threshold as a general policy.
5. **Fidelity changes cannot repair every specification.** The lower-flow case
   exposes the finite range of the adopted characteristic; a more detailed
   hydraulic model does not make negative required opening physical.

The next useful extension is to recover the historical pressure/control and
initialization configuration, then add the evaporator's refrigerant-side
coupling, IHX, and other loop interactions incrementally. Preserve identical
specifications and starting points between strategies, and identify the first
extension that reproduces the difficult solve. Multiple candidate valves would
then let us study where to refine, rather than only whether to refine one valve.
Continuation is a later experiment if direct switching becomes insufficient.
These are research extensions; production hardening is not the next priority.

## Reproducibility and verification

[baseline_summary.json](baseline_summary.json) stores the reviewed per-trial
measurements, solver settings, reference inputs, and diagnostic bound relaxations.
A rerun generates full stage results and solver logs under ignored `results/`.
The integration suite verifies connected switches, unchanged specifications,
energy conservation, agreement with the saved hydraulic point, independent
strategy starts, and both branches of the residual selection rule. Performance
ordering is deliberately not asserted by tests.
