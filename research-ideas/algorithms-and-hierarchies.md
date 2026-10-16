# Algorithm ideas and recursive model representations

These are exploratory research directions, not established novelty claims or
implementation commitments. See [research purpose](README.md) for the current
aims. Equipment contracts remain in [the design documentation](../docs/design.md);
case-specific experiments and results remain with their case studies.

## Working research direction

**Given an engineering question, available measurements, and a hierarchy of
representations, what is the simplest model that supports a sufficiently
reliable answer?**

The intended experimental direction is a bounded heat-pump study that holds
available measurements constant while changing the engineering question, such
as predicting electrical consumption, estimating compressor efficiency, or
sizing the condenser. Investigate whether different questions justify different
representation depths. Define reliability for each question before comparing
selection strategies, using prediction error, uncertainty, or decision quality
as appropriate. This is a direction to develop, not a finalized experiment.

Initialization research should emphasize the wider coupled flowsheet, especially
recycle loops, rather than assume that individual unit operations need better
initializers. Existing unit routines may already work well in isolation. The
potential benefit is using simpler representations to establish mutually
consistent stream states and recycle conditions before introducing detailed
coupling. Physics-informed reconstruction remains a supporting mechanism for
structural expansion, rather than the principal contribution.

Compare direct detailed flowsheet initialization using established unit
routines and a suitable recycle strategy against hierarchical initialization
using the same unit routines where applicable. First establish whether a
flowsheet-level difficulty exists; do not manufacture an initialization
advantage on cases that already solve readily.

## Two main algorithm directions

1. **Adaptive fidelity-path initialization:** choose a sequence of equipment,
   property, and structural changes that reaches a specified target model
   reliably. Compare fixed sequences with adaptive choices, rollback after
   failure, and physics-informed transfer of solution information.
2. **Goal- and data-informed selective refinement:** choose a representation
   that provides useful predictions or decisions at acceptable computational
   cost. Joint equipment/property selection is part of this direction, rather
   than a separate research area. Include deliberate coarsening and fallback
   when appropriate to the operating mode and question.

For initialization, measure success across operating conditions and initial
guesses, total computational effort including failed attempts, and agreement
with the target solution. For selection, measure prediction or decision error,
uncertainty, and total selection plus solve cost. Higher fidelity alone is not
evidence of accuracy.

## Recursive representations: heat-pump example

A heat pump can expose a stable external interface containing source/sink
boundary states and electrical power while offering either:

- An aggregate COP relation and overall energy balances.
- An explicit refrigerant cycle containing compressor, expansion valve,
  condenser, evaporator, and working-fluid properties.

Within the explicit cycle, select compressor efficiency versus performance
maps, isenthalpic throttling versus valve pressure-flow correlations, lumped
versus distributed exchangers, and alternative property formulations.

The representation hierarchy is a tree of choices; the expanded physical
flowsheet is a network with a refrigerant recycle. A selected model can have
different depths in different branches. Structural expansion introduces private
variables and potentially additional specifications and parameters, so the
current fixed-public-DOF switching contract cannot simply be assumed to apply.
Preserve external physical meanings and explicitly define each representation's
required information and specification contract.

## Two proposed policies for opening a detailed representation

### Physics-informed defaults and reconstruction

Use aggregate results and declared assumptions to estimate internal states.
For heating COP, electrical work W implies Q_hot = COP * W and, neglecting
other losses, Q_cold = Q_hot - W. Boundary temperatures, assumed approach
temperatures, temperature changes, fluid properties, and component efficiencies
can then help construct guesses for external flow rates and refrigerant states.
COP, work, and temperature lift generally do not uniquely determine all these
quantities. Record every extra assumption and its role.

Distinguish initial guesses from fixed specifications and uncertain model
parameters. A guess can help a determined nonlinear system converge; it cannot
make an underdetermined system determined. Release temporary initialization
targets before solving the final intended formulation.

### Information-gated expansion

Permit expansion only when measurements or independently known specifications
and parameters support the detailed model. Otherwise retain the aggregate
representation. This is an exploratory policy, not a requirement that every
private variable must be measured: equations can determine unmeasured states.

Represent measurements by physical quantity, operating condition, value,
uncertainty, and location. Treat noisy measurements as observations for
estimation rather than automatically fixing every observed variable exactly.
Check structural determinacy and practical identifiability; measurement count
alone is insufficient.

### Hybrid policy

Use known specifications and data to establish whether expansion is supportable,
then use physics-informed reconstruction to initialize the supported model.
Where assumptions supply missing information, report their effect on prediction
uncertainty. Compare this policy against both extremes above.

## Candidate algorithms

- **Hierarchical initialization:** solve an aggregate model, expand a selected
  branch, reconstruct new states, solve, and accept or roll back. Choose the
  next expansion using solve history and physical feasibility indicators.
- **Measurement-aware selection:** fit the simplest admissible model, inspect
  residuals and target uncertainty, propose supported refinements, and retain
  those that improve held-out prediction or relevant decisions enough to justify
  their cost.
- **Recursive selective refinement:** rank branch expansions and component
  upgrades by expected improvement in the target quantity per added cost.
  Investigate limited look-ahead because opening a cycle may enable a valuable
  child upgrade without providing much immediate benefit itself.
- **Measurement acquisition:** rank additional measurements by expected reduction
  in target uncertainty or their ability to distinguish candidate representations.

## Research questions and experiments

1. When do simpler representations improve initialization of a coupled flowsheet,
   especially with recycles? Compare direct detailed initialization with
   staged expansion using established unit routines in both. Vary recycle
   coupling and operating conditions; assess whole-flowsheet success and total
   effort. Within this experiment, test whether balance-based reconstruction
   improves structural expansion under identical final specifications.
2. What information is sufficient to open a representation? Vary measurement
   location, uncertainty, operating-condition coverage, and independently known
   parameters; assess identifiability and held-out prediction.
3. Should the best representation depend on the engineering question? Compare
   selection for electrical power, outlet temperature, equipment sizing, and
   feasibility constraints using the same available data.
4. Can recursive selection outperform uniform refinement at equal total cost?
   Compare aggregate-only, fully detailed, greedy hierarchical, and limited
   look-ahead strategies. Include selection overhead and failed solves.
5. Can residuals distinguish missing physics from parameter error or measurement
   bias? Use controlled synthetic cases with known injected discrepancies, then
   assess whether conclusions survive realistic noise and model mismatch.
6. When should a branch be coarsened again? Sweep operating conditions and assess
   prediction quality, switching frequency, and the benefit of hysteresis.
7. Which next measurement most improves the decision? Compare targeted sensor
   selection with uniform or random selection under a common measurement budget.

Begin with a bounded steady-state heat-pump case and a small set of candidate
representations. Synthetic data can isolate mechanisms, but data generated by
the same detailed model used for evaluation should be identified as such and
does not establish real-world validity. Keep initialization studies separate
from model-selection studies so numerical success is not mistaken for physical
adequacy.
