# SGHP source-loop results and conclusions

## Main finding: continued analysis through a basic fallback

A shutoff-capable basic valve allows the reduced source-loop analysis to continue
in low-flow cases excluded by the detailed equal-percentage characteristic.
Across both water property models and all four starts, **all 16 low-flow
fallback trials continued successfully**, preserving the original specifications
and mass/energy balances. Their detailed valve residuals remain large, so these
are explicitly **fallback results, not detailed-model validations**.

The research emphasis has shifted accordingly. The normal detailed valve is
already easy to solve in the feasible reduced-loop cases, and the project owner's
experience is that IDAES initialization routines generally work well. These
experiments do not benchmark those routines. There is little value in forcing
this case to demonstrate an initialization advantage. The more useful question
is whether a component needs detailed modeling for the wider analysis at all.

An inactive or noncritical component may warrant a simple relation that permits
continued thermal or operating-mode analysis. The operating context must justify
that choice; a lower model's solver success alone does not establish physical
feasibility of the detailed valve or irrelevance of the component. See the
[research purpose](../../research-ideas/README.md).

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

## Model changes

The three valve formulations share the same inlet/outlet states, Cv, opening,
and common material/energy balances:

- `pressure_flow`: the water-referenced squared flow law with equal-percentage
  opening f(u) = 100^(u-1).
- `linear`: the existing local tangent approximation to that law.
- `basic`: m = K u deltaP, calibrated at the nominal point with
  K = m0/(u0 deltaP0) times Cv/Cv0. It allows zero flow at zero opening and drops
  the detailed opening characteristic and density dependence.

The basic equation is linear in pressure drop at fixed opening, but bilinear
when opening is also calculated. It matches one nominal point, not the detailed
curve over its whole range. It is an alternate coarse model with different
low-flow admissibility, not merely a better starting guess for the same model.
All three preserve the same public DOF and specifications in the experiment.

## Expanded experiment

The updated numerical baseline contains **200 strategy trials**: two property
models, five operating cases, four starts, and five strategies. The property
models are linear water and liquid IAPWS-95. Starts are near-reference, reversed
pressure, equal pressure, and wide-open valve. Every strategy gets a fresh model
and the same initial guesses; no unit initialization solves are hidden.

The operating cases are:

| Case | Flow | Heat removal | Pump power | Pressure anchor |
| --- | --- | --- | --- | --- |
| Reference | Nominal | Nominal | Nominal | 326.866 kPa |
| Higher flow | 120% | Nominal | Nominal | 326.866 kPa |
| Lower pressure | Nominal | Nominal | Nominal | 250 kPa |
| Below control range | 85% | Nominal | Nominal | 326.866 kPa |
| Low demand | 10% | 10% | 10% | 326.866 kPa |

The original 85%-flow case still removes about 46.3 kW, so it must not be called
plant-off operation. The new 10%-load case is a low-demand proxy, not a true
shutdown or a full SGHP dispatch model. Exact zero flow is not studied: a closed
thermal circuit at zero flow would need a different treatment of inactive
states and equipment.

The strategies are direct detailed solving, linear then detailed, residual-based
refinement, basic from the outset, and detailed-first fallback. Fallback is
explicitly permitted only in `below_control_range` and `low_demand`. After a
detailed failure, it retains the current values, selects the basic equation,
and solves without changing specifications or relaxing physical opening bounds.
Successful detailed runs elsewhere are retained. No automatic fallback is built
into the generic mixin or unit model.

Acceptance requires successful termination, nonnegative pressure drop, mass
errors below 1e-6 kg/s, and unit energy errors below 1e-3 W. Detailed validation
requires an active detailed block and normalized detailed residual below 1e-6.
Basic/fallback acceptance instead requires its own normalized residual below
1e-6; detailed disagreement is recorded rather than concealed. Selective tangent
retention uses the original 1e-3 detailed-residual criterion. The output labels
separate detailed validation, retained approximation, basic comparison,
fallback acceptance, and failure.

The environment is Python 3.14.0, IDAES 2.8.0,
Pyomo 6.9.2, and IPOPT 3.13.2. Tolerance is 1e-8, with at
most 200 iterations per stage. Total cost includes failed detailed attempts and
all subsequent solves. Model construction time is separate.

## Results

Counts include all cases; cost medians are over accepted trials. Because basic
and fallback accept additional cases, their median populations differ from those
of direct/staged solving. Wall times are one local sweep and are not a general
performance benchmark.

| Properties | Strategy | Accepted / attempts | Detailed validated | Median total iterations | Median solve seconds |
| --- | --- | --- | --- | --- | --- |
| helmholtz | direct | 12 / 20 | 12 | 5.0 | 0.0491 |
| helmholtz | staged | 12 / 20 | 12 | 3.5 | 0.0621 |
| helmholtz | selective | 12 / 20 | 4 | 3.5 | 0.0366 |
| helmholtz | basic | 20 / 20 | 0 | 5.0 | 0.0504 |
| helmholtz | fallback | 20 / 20 | 12 | 10.0 | 0.0871 |
| linear | direct | 12 / 20 | 12 | 5.5 | 0.0142 |
| linear | staged | 12 / 20 | 12 | 4.5 | 0.0246 |
| linear | selective | 12 / 20 | 4 | 3.5 | 0.0127 |
| linear | basic | 20 / 20 | 0 | 4.0 | 0.0148 |
| linear | fallback | 20 / 20 | 12 | 10.0 | 0.0153 |

For each property model, detailed-first fallback retained 12 detailed solutions
and accepted 8 basic continuations. Combined, that is **24 detailed results and
16 fallback results, with no failed continuation attempts in this grid**.
Direct, staged, and selective strategies still rejected all low-flow cases.
Basic from the outset solved all 40 trials, but none are labeled detailed
validations, even where numerical agreement happens to be close.

The following are basic-model results at the near-reference start. Other starts
converged to the same case-specific values within solver tolerances.

| Properties | Case | Opening | Pressure drop (kPa) | Heat added (kW) | Detailed residual |
| --- | --- | --- | --- | --- | --- |
| linear | below_control_range | 0.02392658 | 151.888194 | 46.093783 | -0.367062 |
| linear | low_demand | 0.00331163 | 129.105230 | 4.609378 | -0.753082 |
| helmholtz | below_control_range | 0.02406658 | 151.004647 | 46.093783 | -0.357948 |
| helmholtz | low_demand | 0.00333100 | 128.354499 | 4.609378 | -0.748723 |

The low-demand case carries 0.114891 kg/s, removes
4.630839 kW, uses
21.461127 W of pump shaft power, and calculates approximately
4.609378 kW of source heat input. Both water models
retain positive, bounded valve opening while satisfying the selected basic law.
The large detailed residuals, around -0.75, make clear that the original detailed
correlation has not been solved.

Fallback provides continuity rather than a demonstrated speed improvement.
For the near-reference start in the low-demand case, linear-water fallback used
53 failed detailed iterations plus 14 basic iterations; choosing basic from the
outset took 3. Helmholtz used 51 plus 14, versus 3 directly with basic. If an
operating-mode decision already establishes that the valve is noncritical,
selecting the coarse model before an expensive failed attempt may be preferable.
The current runner exposes that as the separate `basic` comparison.

## What the thermal agreement does and does not show

With an admissible detailed reference, basic-model source heat input differed by
less than 0.001 W in this sweep. However, this is largely forced by the reduced
model: evaporator duty and pump shaft power are prescribed, and heater duty must
equal their difference. Flow is also prescribed, the valve is adiabatic, and the
tank temperature/pressure anchor fixes the thermal reference. Changing the valve
law primarily changes calculated opening here.

Consequently, these results demonstrate that an otherwise blocking component
model can be replaced while retaining the balances needed to continue this
analysis. They do **not** establish that valve fidelity is unimportant in a
fully coupled SGHP where valve opening may determine circulation, heat transfer,
pump loading, or an engineering decision. Errors relative to a detailed root
are null for the low-flow cases because no admissible reference root was found;
there is no claimed detailed accuracy there.

The original equal-percentage law has f(0)=0.01, whereas the basic law has zero
flow at zero opening. Earlier diagnostic bound relaxations for the 85%-flow case
found required detailed openings approximately -0.0208901 and -0.0196249.
Those unphysical diagnostic solutions remain excluded from strategy statistics.
The basic model changes this range limitation; it does not repair the original
correlation by initialization.

## Research conclusions

1. **Purpose-appropriate fallback is a distinct benefit of multi-fidelity
   modeling.** Continuing an analysis with a consciously chosen coarse model
   can be useful even when returning to the detailed model is neither possible
   nor necessary for that question.
2. **Detailed-model feasibility and continued-analysis acceptance are different
   claims.** Preserve public quantities, specifications, and balances, and report
   which model produced the result and why it was accepted.
3. **Criticality should influence selection.** A residual-only rule would reject
   these basic solutions or force an infeasible upgrade. Operating-mode context
   and effects on the quantities of interest must also inform a fallback policy.
4. **Low flow is not proof of inactivity.** The original stress case is not off.
   The low-demand proxy is closer to the intended motivation but still does not
   establish the real plant's operating mode. Eligibility is an explicit research
   assumption in this case study.
5. **Initialization remains an aim, not a result to manufacture.** The feasible
   detailed valve cases already solve readily. This case is more informative for
   selective model adequacy and continued analysis than for proving superior
   initialization.

The next useful experiment is to restore wider SGHP coupling and define an
engineering quantity or decision whose sensitivity to the valve can be measured.
Compare fallback when the component is active/critical against an inactive or
low-demand mode, and determine when the simpler law changes that decision.
Actual shutdown will require an explicit inactive-equipment model or mode; it
should not be inferred from this nonzero-flow experiment. Retain the current
explicit sequences until additional research cases justify shared policy code.
Production hardening remains outside the priority scope.

## Reproducibility and verification

Inputs, all 200 per-trial outcomes, first-stage termination codes, fallback
reasons, residuals, costs, and diagnostic relaxations are recorded in
[baseline_summary.json](baseline_summary.json). Full stage logs are generated
under ignored `results/`. See [README.md](README.md) for reproduction commands.
Integration tests verify shared-variable switching, preserved specifications,
conservation, detailed-reference agreement where available, selection branches,
and low-flow continuation with a visibly unvalidated detailed correlation.
