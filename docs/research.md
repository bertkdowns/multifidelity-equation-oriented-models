# Research purpose

This is an academic research project investigating multi-fidelity process
models. Its purpose is to explore algorithms and demonstrate research ideas,
with clear, understandable implementations.

## Primary aims

1. **Initialization through fidelity changes.** Investigate whether solving
   simpler equipment and property formulations first can help initialize more
   detailed flowsheet models. Study the sequence of fidelity changes, transfer
   of useful solution information, and resulting convergence behavior.
2. **Selective refinement.** Investigate when and where a flowsheet needs more
   detailed equipment or property models. Refine the parts that matter to a
   chosen engineering result or constraint while retaining simpler formulations
   elsewhere.

Equipment and property fidelity are independent choices. Experiments should
distinguish their effects and identify when additional detail changes the result.
Higher fidelity is not automatically more accurate; comparisons need a stated
reference and an engineering quantity of interest.

## Evidence to pursue

Compare fidelity strategies against direct initialization and solving of a
detailed reference model. Track initialization success, computational effort,
and agreement in the quantities or decisions that matter to the experiment.
For selective refinement, investigate whether a selection criterion identifies
where extra detail is necessary and avoids unnecessary refinement elsewhere.

## Scope and implementation priorities

Prioritize changes that enable these experiments, clarify the modeling
contracts, or make research results reproducible. Keep the code focused on
shared physical interfaces, explicit equations, fidelity selection, and the
algorithms being studied.

General robustness, production hardening, broad compatibility, and elaborate
frameworks are not goals in themselves. Add them when a concrete research
experiment requires them or when their absence would invalidate its results.
Bounded operating domains, simple heuristics, and documented limitations are
acceptable at this stage.

Tests should verify the main contracts and research-relevant outcomes through
integration. Before adding complexity, ask: **which research aim or experiment
does this enable, and what evidence will show that it helped?**
