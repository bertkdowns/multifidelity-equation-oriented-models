# Coupled SGHP model selection

Rebuild the complete steam-generating heat pump, including its refrigerant
cycle, IHX, source circuit, flash-steam circulation, warm-water recovery, and
makeup flows. Give at least every valve and heat exchanger a shared public
interface with lower and higher fidelity formulations.

The central question is: **how much detailed physics can we retain while making
a coupled flowsheet solvable, and what changes in the outputs we care about?**
Useful continuation with an explicit approximation is an outcome in its own
right; initialization to the all-high model is a separate objective. Existing
IDAES initialization routines may already work well, so do not manufacture an
initialization advantage on easy unit problems.

The [implemented first study](../case_studies/sghp/FULL_STUDY.md) compares uniform,
manual, progressive, failure-driven, residual-guided, structure-guided, and
operating-context choices, including upgrades of coupled equipment groups.
It uses a reconstructed steady rating problem, not a historical MSS replay.
[Results](../case_studies/sghp/FULL_RESULTS.md) should guide subsequent work.

## What evidence matters

- Solve success across operating conditions and starting states.
- Total computational effort, including failures and selection overhead.
- Which detailed formulations remain, and why an approximation was accepted.
- Steam production, dry-steam production, compressor power, COP, and heat duties,
  with identical mathematical meanings across representations.
- Output differences where an all-high reference exists; unresolved validity
  where it does not. Higher fidelity alone is not evidence of physical accuracy.

Count and weighted importance of detailed units are possible objectives, not
interchangeable measures of accuracy. A greedy search that retains eight of
nine detailed units is not automatically optimal or more useful than a simpler
model with better predictions for the requested analysis.

## Questions to investigate next

1. Can numerical or structural evidence select useful candidates without already
   knowing the difficult source valve? Large failed-iterate residuals can be
   misleading; DM determinacy and strongly connected groups describe structure,
   not the cause of numerical failure.
2. When should units switch together? Compare single changes, coupled groups,
   and limited look-ahead; a group may enable convergence but discard much more
   detail than necessary.
3. What happens when the all-low model cannot describe an operating mode? Search
   from mixed configurations as well as uniform baselines. Heat-flow reversal,
   phase change, and inactive branches can make the coarsest representation
   inappropriate even though it has fewer equations.
4. Can output- or goal-aware selection retain only the detail needed for steam
   production or power prediction? Introduce error budgets and independent
   measurements instead of accepting solely on solvability and conservation.
5. How do conclusions change when measured controls, pressure coupling,
   operating rows, and validated equipment parameters replace the current
   calibration assumptions? Keep reconstruction error separate from selection
   behavior and discretization effects.
6. Does switching help full-flowsheet initialization compared with established
   IDAES unit routines and a comparable recycle strategy? That requires a
   separate controlled benchmark; direct simultaneous solves do not answer it.
7. Does selection generalize across examples? The present source-valve failure
   has a known answer, favoring informed policies. Include multiple flowsheets
   and operating conditions with different model weaknesses, and less clear-cut
   cases involving interacting limitations. Keep case-specific answers out of
   general selection algorithms and distinguish informed from blind policies.
8. Can explicit activation conditions guide selection? Separate validity domains
   (such as a detailed correlation requiring sufficient flow) from permission
   to approximate (such as a simplified model having negligible effect on a
   chosen output at low flow). Explore MINLP formulations with discrete fidelity
   choices and conditional equations/domain constraints, alongside metaheuristics
   that search admissible assignments. Enforce conditions on solved operating
   states, since switching can itself change flow. Study threshold selection,
   domain overlap/gaps, and output relevance rather than treating low flow as
   automatic evidence that an approximation is adequate.

The source-loop case remains a controlled example. This coupled study is the
next layer, alongside the broader electrical-consumption prediction direction.
Keep implementation focused on these academic questions rather than building a
production workflow engine or broad compatibility framework.
