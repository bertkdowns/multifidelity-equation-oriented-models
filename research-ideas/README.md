# Research purpose

This directory collects research aims and exploratory directions. See
[algorithm ideas and recursive representations](algorithms-and-hierarchies.md)
for adaptive initialization, selective refinement, and measurement-aware
hierarchical heat-pump models.

The emerging unifying question is: **given an engineering question, available
measurements, and a hierarchy of representations, what is the simplest model
that supports a sufficiently reliable answer?** Initialization work should
focus on coupled flowsheets and recycle loops, where simpler representations
may help establish consistent states, while making use of established
individual-unit initialization routines.

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
   elsewhere. This includes using an explicitly chosen low-fidelity fallback
   to continue analysis when a detailed component model is not important to the
   current operating mode or question.

Equipment and property fidelity are independent choices. Experiments should
distinguish their effects and identify when additional detail changes the result.
Higher fidelity is not automatically more accurate; comparisons need a stated
reference and an engineering quantity of interest.

## Purpose-specific fallback

A useful result does not always require every component to end at its highest
fidelity. An inactive or noncritical valve may need only a basic hydraulic
relationship to keep the wider analysis moving. A detailed characteristic can
exclude low-flow operation that a coarse, shutoff-capable model admits. Treat
this as an explicit change of modeling assumptions, with unchanged physical
balances and specifications, rather than as successful initialization of the
original detailed formulation.

Record which components use fallback, why that choice is appropriate to the
research question, and the quantities of interest that remain usable. A fallback
result must remain distinguishable from detailed-model validation; a large
detailed-model residual does not automatically invalidate a deliberately chosen
fallback, but cannot be hidden or claimed as detailed agreement.

For the SGHP valve case, the current research priority is this ability to
continue analysis. Feasible reduced-loop cases already solve readily with the
normal valve. Experience with IDAES initialization also motivates avoiding an
artificial search for an initialization advantage. The present experiments do
not benchmark IDAES initialization routines. Low flow alone does not establish
that a whole plant is off or that a component is unimportant; that assessment
belongs to the operating context and research question.

## Evidence to pursue

Compare fidelity strategies against direct initialization and solving of a
detailed reference model. Track initialization success, computational effort,
and agreement in the quantities or decisions that matter to the experiment.
For selective refinement, investigate whether a selection criterion identifies
where extra detail is necessary and avoids unnecessary refinement elsewhere.
For fallback, track continued solvability, conservation, explicit model choices,
and effects on relevant engineering outputs. Where the detailed model has no
admissible solution, do not invent a detailed reference error; use independent
balances and scenario requirements, and state the remaining validity limits.

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
