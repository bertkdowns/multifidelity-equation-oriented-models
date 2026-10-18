# Complete SGHP study: results and conclusions

The complete topology reconstruction solves at the reference point. In the
low-flow cases, **selective source-valve fallback continues analysis while
retaining the other eight high-fidelity units**. Uniform simplification is not
universally sufficient: the low-demand mixed solution reverses IHX heat flow,
which the present coarse exchanger cannot represent.

These are results for a calibrated research rating model, not validation of the
historical SGHP or a replay of its controls. The [study definition](FULL_STUDY.md)
records topology, equations, calibration, specifications, domains, and algorithms.
The earlier [source-loop results](RESULTS.md) remain a separate controlled study.

## Experiment and comparison

The [reviewed baseline](full_baseline_summary.json) contains **72 trials and
188 attempted solves**: four operating cases, two starts, and nine strategies.
Each trial has a fresh model and identical case/start specifications. All five
exchangers and four valves are selectable; phase-capable water/n-butane
properties remain fixed throughout each trial.

IPOPT uses a common 80-iteration/8-CPU-second limit per attempt and common unit
scaling. Failed attempts count toward cost. Timings are from one local sweep;
CPU cutoffs can affect the failed point and subsequent residual ranking. These
are illustrative research comparisons, not stable performance rankings. Pyomo
can label CPU-limit exits `maxIterations`; the generated logs distinguish the
messages. Tests do not assert iteration counts or timings.

### Definition of accepted

**Accepted means a converged, numerically consistent solution of the selected
fidelity assignment.** A solve must pass Pyomo's `check_optimal_termination`
check and every acceptance check below, implemented in
[`full_experiments.py`](full_experiments.py):

| Check | Required value |
| --- | --- |
| All recorded diagnostic metrics | Finite |
| Maximum absolute equation violation after applying the study's scaling factors | < 1e-6 |
| Maximum variable-bound violation after scaling | < 1e-6 |
| Minimum exchanger temperature approach oriented in the direction of its signed heat duty | ≥ −1e-4 K |
| Absolute whole-flowsheet energy imbalance | < 0.01 W |
| Maximum mass-equation violation | < 1e-6 kg/s |
| Maximum energy-equation violation | < 0.01 W |

The directional temperature check allows consistent heat-flow reversal, including
negative IHX duty. Scaled tolerances use the unit-based factors defined in
[`scale_model()`](full_flowsheet.py); they are distinct from the dimensional
mass/energy tolerances above.

“Accepted / 8” counts trials ending with an accepted assignment, including a
previously accepted solution restored after a failed refinement. It does not
require every intermediate solve to succeed. An accepted assignment is labeled
`all_high_solution` when all nine choices are high, or `accepted_approximation`
when any choice is low.

Acceptance does **not** require agreement with inactive high-fidelity equations,
an output-error budget, or experimental plant data. It establishes consistency
under the chosen equations and checks, not physical accuracy or suitability for
every engineering question.

### Strategy comparison

| Strategy | Accepted / 8 | High units retained when accepted | Median total iterations | Median solve seconds | Median whole-trial seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| All high | 2 | 9 / 9 | 49 | 6.356 | 8.445 |
| All low | 6 | 0 / 9 | 8.5 | 0.307 | 2.183 |
| Manual source fallback | 8 | 8 / 9 | 7 | 0.718 | 2.791 |
| Progressive refinement | 6 | 8–9 / 9 | 101.5 | 8.881 | 11.107 |
| Failure-driven relaxation | 8 | 8–9 / 9 | 58.5 | 6.955 | 8.970 |
| Residual-guided relaxation | 7 | 3–9 / 9 | 102.5 | 12.924 | 14.985 |
| Structure-guided relaxation | 6 | 0–9 / 9 | 108 | 9.494 | 11.543 |
| Operating context | 8 | 8–9 / 9 | 7 | 0.884 | 2.881 |
| Grouped refinement | 6 | 8–9 / 9 | 80.5 | 7.577 | 9.591 |

Cost medians include all eight trials, including unsuccessful trials; fidelity
counts include accepted trials only. Whole-trial time includes construction,
structural analysis, selection overhead, and every solve. Structural analysis is
performed for every trial, including uniform baselines. The first trial also
pays process startup/property-data setup costs. Across all strategies, 57 final
assignments were accepted; these are not 57 independent operating conditions.

## Why all-high fails below the source control range

The source specifications determine its hydraulic pressure drop independently
of the thermal rating solution. A [solver-free check](data/full_source_control_range.json)
combines pump fluid work with the detailed valve law:

```text
h_pump_out = h_tank + W_source / m_source
DP = W_source eta_source rho_pump_out / m_source
u_required = 1 + ln(m_source / (Cv sqrt(DP rho_source 999))) / ln(100)
```

| Case | Required detailed opening | Within [0, 1]? |
| --- | ---: | --- |
| reference | 0.03331020 | Yes |
| below_control_range | -0.01962514 | No |
| low_demand | -0.46668980 | No |
| reduced_source_flow | -0.13307461 | No |

Thus the three low-flow cases conflict with the adopted equal-percentage
characteristic and opening bounds. Solver failure alone would not establish
this; the independent rearrangement does. The basic shutoff-capable law admits
an alternative solution. It does **not** repair initialization of the same
bounded detailed equation.

The source-first failure-driven strategy solves all eight trials, retaining
nine high units at reference and eight in the six low-flow trials. Operating
context reaches the same representation choices without first paying for the
known detailed failure. Both policies benefit from prior knowledge of the
source-valve issue; this is not evidence that a blind search has identified it.
Manual fallback also solves all eight, but unnecessarily simplifies the source
valve at reference.

## Residual and structural guidance can discard too much detail

For the near-reference start at 85% source flow, residual-guided relaxation
retains only **three** high units, while structure-guided relaxation retains
**none**. Both obtain an accepted approximation, but source-first relaxation
retains eight. At 60% source flow with the same start, the respective counts
are three, one, and eight. The perturbed start yields different failed points
and more favorable residual rankings in these cases.

The initial all-high DM decomposition is square and fully matched: 258
variables/equalities, with no unmatched, underconstrained, or overconstrained
partitions. Mapped/merged equation SCCs give three switching groups: source
valve; steam valve; and a seven-unit group containing all exchangers plus the
expansion and hot-water valves. Simplifying that large group can remove much
more detail than necessary.

DM therefore helps describe determinacy and coupling, but does not identify
this bounded nonlinear control-range conflict. Large scaled residuals at a
failed iterate also do not identify the responsible component: the coupled
thermal equations can have large residuals when the source valve is the known
admissibility problem. Neither heuristic is a causal diagnosis.

## An all-low start is not always an appropriate starting model

Both low-demand all-low trials fail under the common solve budget. Progressive
and grouped refinement consequently fail before any upgrade is attempted.
Yet mixed source-valve fallback with the detailed IHX solves from both starts.
Its IHX duty is about **−284.6 W**, versus about +678.6 W at reference. The
consistent reversal is allowed by the high exchanger and acceptance checks;
the coarse Chen formulation has positive terminal-difference bounds.

This shows a concrete mode the coarse exchanger cannot represent. It does not
prove that every possible all-low root is infeasible: the experiment establishes
failed all-low solves and a successful mixed root with reversal. The next useful
algorithm direction is mixed starting configurations and mode-aware selection,
rather than assuming all-low is always a safe initialization baseline.

At low demand, residual-guided relaxation fails from the reference start and
succeeds with seven high units from the perturbed start. Structure-guided
relaxation fails from both. Known-source fallback retains eight high units and
succeeds from both. These outcomes favor using operating knowledge in this
particular case, not a universal preference for manual policies.

## Changes in engineering outputs

At reference, the all-high model predicts:

- Steam outlet: **0.02099474 kg/s**, including **0.01905815 kg/s vapor**.
- Compressor work: **12.91685 kW**.
- Heating COP: **4.31148**; steam COP: **3.68083**.

The captured point has 0.0209915 kg/s steam outlet and 12.91648 kW compressor
work. Close agreement checks the reconstruction around its fitted point, not
independent predictive accuracy.

Relative to that all-high solution, the accepted all-low reference result changes
steam outlet by **-1.507%**, dry-steam flow by **-1.663%**, heating COP by
**+0.736%**, and compressor work by **-1.161%**.
Conservation and solvability therefore do not establish that simplification is
adequate for a particular output-error budget.

The known-source mixed benchmark gives the following calculated outputs:

| Case | Steam outlet kg/s | Dry steam kg/s | Heating COP | IHX duty W |
| --- | ---: | ---: | ---: | ---: |
| reference | 0.02099474 | 0.01905815 | 4.31148 | 678.606 |
| below_control_range | 0.02091283 | 0.01897606 | 4.30760 | 787.264 |
| low_demand | 0.00189915 | 0.00170506 | 4.77122 | -284.606 |
| reduced_source_flow | 0.01926921 | 0.01732888 | 4.23642 | 2906.729 |

Across accepted results, the maximum global energy imbalance is
7.28e-11 W and the maximum external mass imbalance is
0 kg/s. All satisfy the declared equation, bound, balance,
and directional temperature checks. These checks establish consistency under
the selected model, not physical accuracy of its approximations.

All-high reference errors remain **null** for the three low-flow cases: no
admissible all-high reference exists under the adopted source specifications.
The mixed results above are conditional benchmarks, not substitutes for that
missing validation reference.

## Conclusions and next steps

1. **Selective continuation is demonstrated on the complete topology.** The
   source-valve fallback permits useful coupled calculations while retaining
   detailed thermal representations. It deliberately changes model admissibility.
2. **Uniform simplification is not automatically safe.** Phase behavior and
   operating-mode changes can require a detailed component even at low load.
   The reversing IHX is the immediate example.
3. **Residuals and structural groups are useful evidence, not sufficient policies.**
   In this small study they can select unnecessary simplifications or miss the
   useful mixed configuration. Test candidate probing, mixed seeds, alternative
   orders, and limited look-ahead next.
4. **No initialization advantage is established.** Both all-high reference starts
   already solve directly; progressive refinement spends more work to reach the
   same target. This is not a comparison with established IDAES unit/recycle
   initialization routines.
5. **The next selection objective should include engineering outputs.** Count of
   high units is a convenient metric, not accuracy. Compare output-error budgets,
   weighted component relevance, and retained detail at a common total effort.

The current pressure/flow anchors make source-valve simplification change its
required opening without changing the thermal rating at reference. This is a
property of the chosen specification problem, not a general conclusion that
valves are unimportant. The low-demand proxy still produces steam; it must not
be described as an off plant. More realistic control/specification choices,
operating rows, validated valve/UA parameters, and pressure coupling are needed
before claiming plant relevance.

Four-cell high exchangers are not mesh-converged reference physics. The steam
hydraulic relation omits choking and wet-steam corrections. Properties are fixed
rather than selected, and the compressor, pumps, mixing/splitting, and flash
models have one formulation each. These declared limitations define subsequent
research work; they do not call for a general production-hardening framework.

The executable inputs, calibration, snapshot, control-range diagnostic, and
reviewed trial/attempt records accompany this report. Generated solve logs are
under ignored `results/full_reviewed/` for this sweep. Integration tests cover
conservation, common DOF/specifications, low-flow mixed solutions, and rollback
of failed refinement, rather than freezing solver internals or algorithm rankings.
