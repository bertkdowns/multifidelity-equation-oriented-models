# Literature review: information-supported, purpose-specific process models

Reviewed 4 November 2026. This is a focused, exploratory review, not a systematic review or a proof of novelty. It follows the questions in [research purpose](README.md), [algorithms and hierarchies](algorithms-and-hierarchies.md), [information-directed specification](information-directed-specification.md), and [initialisation](initialisation.md). Terminology follows the [model-language glossary](../src/multifidelity/model_language/terminology.md).

## Main finding

The project sits at the intersection of several established research areas: goal-oriented model adaptivity, grey-box model structure selection, process-data observability/reconciliation, and continuation-based initialization. The strongest opportunity is to investigate how these ideas interact in a reusable process-model hierarchy: **which representation and independent specifications are justified by the available evidence for a particular engineering prediction?** The broad idea of starting simple and adding useful detail already has substantial prior art.

Three especially close starting points are Domschke et al. on selective physical-model refinement in gas networks; Bacher and Madsen on data-supported selection through a thermal-model hierarchy; and Liu and Cai on limiting heat-pump model parameters to what sparse measurements can support. Parker et al. supplies the directly relevant DM foundation. These should be central references, rather than treating the work simply as another surrogate-model multifidelity study.

## Scope and reading record

Searches covered primary publisher records, author manuscripts, university repositories, arXiv and official framework documentation. Search-result dates were not treated as publication dates. “Full-text sections” below means the accessible paper was opened and relevant methods/application passages were read; it does not mean every proof or every page was studied. Abstract-only sources support narrower conclusions. No inaccessible paper is represented as fully read.

The repository distinguishes selecting an implementation, choosing specifications, initializing a numerical instance, and assessing predictions. This review preserves those distinctions. In particular, the present trust ranks are ordinal preferences, not measurement variances, and DM completeness is not statistical identifiability or numerical solvability.

## Closest methodological literature

### 1. Selective model refinement in physical networks

**Domschke, Dua, Stolwijk, Lang and Mehrmann (2017), “Adaptive Refinement Strategies for the Simulation of Gas Flow in Networks using a Model Hierarchy.”** [Author full text](https://arxiv.org/html/1701.09031), arXiv:1701.09031. **Read:** introduction, model hierarchy and adaptive loop, refinement formulation.

Each pipe can use an algebraic, semilinear or nonlinear isothermal-flow model. Dual-weighted residual estimates guide physical-model, spatial and temporal refinement against a functional tolerance; the loop can subsequently coarsen. Refinement cost versus estimated error reduction is formulated as a generalized knapsack problem and approached with greedy strategies. This is very close prior art for component-wise selective refinement. [Source](https://arxiv.org/html/1701.09031)

**Project implication:** use it as a benchmark for benefit-per-cost ranking and coarsening. Our proposed distinction is that expansion may also change information requirements and internal topology; its error estimators do not automatically carry across to calibrated, structurally different heat-pump models. Investigate that distinction rather than claiming local fidelity selection itself is new.

### 2. Goal-oriented hierarchical modeling

**Oden, Prudhomme and Bauman (2004 report; 2005 journal paper), “On the Extension of Goal-Oriented Error Estimation and Hierarchical Modeling to Discrete Lattice Models.”** [University full text](https://www.oden.utexas.edu/media/reports/2004/0437.pdf), [journal record](https://www.sciencedirect.com/science/article/abs/pii/S0045782504004487). **Read:** introduction and Section 2, with adaptive-modeling examples screened.

The paper relates error in a chosen quantity of interest to residuals weighted by a dual influence problem, then uses this in hierarchical continuum/lattice modeling. It provides a mathematical precedent for allocating model detail according to a desired output rather than uniformly improving the whole state. The demonstrated setting is a specific mechanics hierarchy, not arbitrary process-model replacement. [Source](https://www.oden.utexas.edu/media/reports/2004/0437.pdf)

**Project implication:** a raw component residual should not be the refinement score by itself. A useful future estimator would assess how that discrepancy propagates to electrical power, condenser sizing or another target. Initially, test candidate upgrades directly on held-out predictions; derive adjoint estimates only where the candidate equations and state transfers justify them.

### 3. Data-supported growth of a thermal-model hierarchy

**Bacher and Madsen (2011), “Identifying suitable models for the heat dynamics of buildings,” Energy and Buildings 43, 1511–1522.** DOI [10.1016/j.enbuild.2011.02.005](https://doi.org/10.1016/j.enbuild.2011.02.005); [author full text](https://henrikmadsen.org/wp-content/uploads/2014/05/Journal_article_-_2011_-_Identifying_suitable_models_for_the_heat_dynamics_of_buildings.pdf). **Read:** introduction, Sections 4–5 including selection and measurement design.

This study constructs a hierarchy of thermal grey-box models and applies forward selection with likelihood-ratio tests, residual checks and physical interpretation. The authors explicitly require model complexity to match information in the data, and retain a role for engineering judgment. Their experimental heating signal excites the relevant dynamics. Parameters can change physical meaning between model levels. [Source](https://henrikmadsen.org/wp-content/uploads/2014/05/Journal_article_-_2011_-_Identifying_suitable_models_for_the_heat_dynamics_of_buildings.pdf)

**Project implication:** this is a strong baseline for information-gated expansion. Statistical improvement and engineering adequacy are different tests; likelihood-ratio assumptions also need checking before using them for nonnested aggregate-versus-cycle candidates. Preserve physical quantity meanings across levels, rather than blindly copying similarly named parameters.

### 4. Heat-pump models under limited training data

**Liu and Cai (2021), “A robust gray-box modeling methodology for variable-speed direct-expansion systems with limited training data,” International Journal of Refrigeration 129, 128–138.** DOI [10.1016/j.ijrefrig.2021.05.007](https://doi.org/10.1016/j.ijrefrig.2021.05.007); [publisher abstract and introduction](https://www.sciencedirect.com/science/article/abs/pii/S0140700721001705); [author manuscript](https://jcai.oucreate.com/wp-content/uploads/2022/07/paper_V20-no-marked-changes.pdf). **Read:** publisher abstract/introduction; manuscript fetch timed out.

Component models are trained separately and then coupled through continuity constraints for system-level training. Sensitivity ranking and decorrelation reduce the fitted parameter set according to data quality. A variable-speed heat-pump case examines different training-set sizes. This directly addresses the risk that extra model parameters exceed available information. [Source](https://www.sciencedirect.com/science/article/abs/pii/S0140700721001705)

**Project implication:** distinguish physical representation selection from parameter-subset selection. Include a detailed model with a small, supported fitted parameter set as a baseline; otherwise a selector might appear successful merely because the detailed comparator is overparameterized. The paper motivates testing data coverage and correlation, not measurement count alone.

### 5. Prediction-focused parameter/model simplification

**Eghtesadi, Wu and McAuley (2013), “Development of a Model Selection Criterion for Accurate Model Predictions at Desired Operating Conditions,” Industrial & Engineering Chemistry Research 52, 12297–12308.** DOI [10.1021/ie302408b](https://doi.org/10.1021/ie302408b). **Read:** publisher abstract/metadata; direct full-text access blocked.

The stated problem is selecting parameters to estimate when process data cannot support all kinetic, thermodynamic and mass-transfer parameters. Simplifying assumptions or fixing parameters at prior nominal values may improve prediction with sparse, noisy or correlated data. It is an especially relevant lead for the desired-operating-condition aspect of this project. [Source](https://pubs.acs.org/doi/10.1021/ie302408b)

**Project implication:** read the full method before designing a new prediction-oriented selection score. Include operating-envelope transfer tests: a model suitable around calibration points may fail at a different temperature lift or compressor speed.

### 6. Purpose-driven multifidelity industrial models

**Christoph Bergs (2020), “Multi-Fidelity Modeling of Dynamic Systems for Operation-Parallel Simulation,” doctoral thesis, KIT.** [University full text](https://publikationen.bibliothek.kit.edu/1000123045/88145691). **Read:** summary, fusion-method discussion including moSAIc, purpose-driven design and industrial-case passages.

The thesis combines physical models of different fidelities with observations through model/data fusion. Its purposes include soft sensing, accuracy enhancement and transfer between related systems; cases include motor temperatures, valve pressure drop and motor-fleet monitoring. moSAIc learns context-dependent weights for combining model outputs. [Source](https://publikationen.bibliothek.kit.edu/1000123045/88145691)

**Project implication:** this is related purpose-driven industrial modeling, but the inspected approach centers on fusion rather than selecting recursive equation relationships and independent specifications. Soft sensing is a promising application: expose the requested hidden quantity only when the evidence and model support it. Do not assume a fusion model automatically preserves process balances.

### 7. Broader multifidelity context

**Peherstorfer, Willcox and Gunzburger (2018), “Survey of Multifidelity Methods in Uncertainty Propagation, Inference, and Optimization,” SIAM Review 60, 550–591.** [Author full text](https://kiwi.oden.utexas.edu/papers/multi-fidelity-survey-peherstorfer-willcox-gunzburger.pdf), [arXiv record](https://arxiv.org/abs/1806.10761). **Read:** abstract, introductory scope and taxonomy; a survey rather than an original application experiment.

The survey organizes multifidelity methods into adaptation, fusion and filtering for expensive outer-loop tasks. A common premise is retaining a high-fidelity model to establish accuracy or convergence properties while using cheaper models to reduce cost. [Source](https://kiwi.oden.utexas.edu/papers/multi-fidelity-survey-peherstorfer-willcox-gunzburger.pdf)

**Project implication:** this repository's explicit physical alternatives fit most naturally with model adaptation/management. A declared “high fidelity” reference is not experimental truth; validate its calibration and domain separately. A selected fallback that cannot satisfy the detailed equations needs its own adequacy argument.

## Specification, observability and noisy measurements

### 8. Direct foundation for DM-based analysis

**Parker, Nicholson, Siirola and Biegler (2023), “Applications of the Dulmage–Mendelsohn decomposition for debugging nonlinear optimization problems,” Computers & Chemical Engineering 178, 108383.** DOI [10.1016/j.compchemeng.2023.108383](https://doi.org/10.1016/j.compchemeng.2023.108383); [repository manuscript](https://www.osti.gov/servlets/purl/1996187). **Read:** publisher abstract/highlights; repository full-text retrieval failed.

The paper uses equation–variable bipartite graphs to expose structurally underdetermined and overdetermined subsets and documents Pyomo/JuMP implementations. It is directly relevant to the repository's existing incidence-analysis machinery. [Source](https://www.sciencedirect.com/science/article/pii/S0098135423002533)

**Project implication:** cite DM specification selection as an application built on established structural analysis. The remaining experimental question is whether trust-prioritized admissible choices improve useful specifications, assumption use or predictive performance. Structural matching alone does not establish that the nonlinear Jacobian has adequate numerical rank at the operating point.

### 9. Data reconciliation and variable classification

**Crowe (1996), “Data reconciliation—Progress and challenges,” Journal of Process Control 6, 89–98.** DOI [10.1016/0959-1524(96)00012-1](https://doi.org/10.1016/0959-1524(96)00012-1). **Read:** publisher abstract. This review treats measured process data as error-contaminated and adjusts it subject to conservation and other constraints; observability, redundancy and gross errors are central issues. [Source](https://www.sciencedirect.com/science/article/pii/0959152496000121)

**Mitsas (2010), “Data reconciliation and variable classification by null space methods.”** DOI [10.1016/j.measurement.2009.12.032](https://doi.org/10.1016/j.measurement.2009.12.032). **Read:** publisher abstract/section excerpts, through the companion research pass. Jacobian SVD/null-space analysis provides a numerical route to variable classification and sensor-network assessment. [Publisher](https://www.sciencedirect.com/science/article/abs/pii/S0263224110000084)

**Project implication:** the present hard-fix selector is a bounded approximation to using information, not a replacement for reconciliation. Compare it with constrained weighted estimation when noise is introduced. Keep ordinal trust, uncertainty covariance, bias detection and structural independence separate. Before investigating specification replacement, scale variables and residuals and evaluate numerical sensitivity at meaningful states.

### 10. Prediction uncertainty can be more useful than parameter certainty

**Kreutz, Raue and Timmer, “Likelihood based observability analysis and confidence intervals for predictions of dynamic models.”** [Author preprint](https://arxiv.org/html/1107.0013), arXiv:1107.0013 (2011). **Read:** motivation and prediction-profile method/examples.

Prediction profile likelihood constrains a candidate predicted value and reoptimizes nuisance parameters to assess its compatibility with observations. This addresses prediction uncertainty without requiring each parameter estimate to be unique; the paper develops the method for mechanistic dynamic models. [Source](https://arxiv.org/html/1107.0013)

**Project implication:** avoid rejecting every representation whose internal parameters are poorly identified if the requested electrical power remains well constrained. Conversely, a well-fitted model can leave the requested hidden state uncertain. Initially use uncertainty diagnostics suited to the small steady-state problem, then assess whether prediction profiling is computationally worthwhile.

Related foundational lead: **Raue et al. (2009), “Structural and practical identifiability analysis of partially observed dynamical models by exploiting the profile likelihood,”** DOI [10.1093/bioinformatics/btp358](https://doi.org/10.1093/bioinformatics/btp358). **Read:** bibliographic record/abstract, not full text. [Primary abstract record](https://pubmed.ncbi.nlm.nih.gov/19505944/)

## Initialization and the baseline that must be beaten

### 11. Simplified-to-detailed initialization is established

**Sielemann et al. (2011), “Robust Initialization of Differential-Algebraic Equations Using Homotopy.”** [Conference full text](https://2011.international.conference.modelica.org/proceedings/pages/papers/04_1_ID_154_a_fv.pdf). **Read:** abstract and opening approach; detailed examples screened. The paper introduces the Modelica homotopy approach for difficult DAE initialization with mechanical, electrical and fluid examples. [Source](https://2011.international.conference.modelica.org/proceedings/pages/papers/04_1_ID_154_a_fv.pdf)

**De Pascali and Casella (2024 preprint), “Steady-State Initialization of Object-Oriented Advanced Thermal Power Generation System Models with Application to the Case of the SOS-CO2 Cycle.”** [Full text](https://arxiv.org/html/2411.12666). **Read:** initialization strategy, Sections 3–4 and system-boundary discussion screened. A later journal version is indexed under DOI [10.1080/13873954.2026.2616725](https://doi.org/10.1080/13873954.2026.2616725); the preprint is the version inspected.

The inspected strategy simplifies nonlinear equations and breaks critical equation couplings before continuation restores the actual model. Structural decomposition then enables smaller sequential solves. The authors discuss scaling, strong components and possible singularities along the homotopy path. [Source](https://arxiv.org/html/2411.12666)

**Project implication:** the research distinction may be changing representation topology and transferring consistent physical states through a semantic hierarchy, not simply solving an easier model first. Compare against valid defaults, existing provider initializers, block triangularization and homotopy where applicable. A semantic tree does not necessarily capture the numerical strongly connected components of a recycle.

### 12. Existing process-model infrastructure

**Lee et al. (2021), “The IDAES process modeling framework and model library—Flexibility for process simulation and optimization.”** DOI [10.1002/amp2.10095](https://doi.org/10.1002/amp2.10095). **Read:** official article description and publisher hierarchy passages, not full paper. IDAES already provides compositional process modeling and a model-library framework. [Official publication page](https://idaes.org/the-idaes-process-modeling-framework-and-model-library-flexibility-for-process-simulation-and-optimization/)

For an implementation baseline, inspect the official [IDAES block triangularization initializer](https://idaes-pse.readthedocs.io/en/2.8.0/reference_guides/initialization/bt_initializer.html). The repository itself already identifies this comparator. Reuse native unit initialization expertise rather than attributing benefits from those routines to a new hierarchy algorithm.

## Applications with a concrete reason to use these techniques

The following are **proposed applications inferred from the reviewed work**, not claims that this repository has demonstrated them.

| Application and engineering decision | Why this particular approach could help | Useful test and principal limitation |
| --- | --- | --- |
| Industrial heat-pump electrical-power forecasting at changing source/sink conditions | Start from calibrated COP; introduce cycle/compressor detail only if it improves held-out power and available measurements support its parameters. This matches the current first experiment and the Liu–Cai sparse-data problem. | Compare power error across temperature lift, load and speed; test interpolation separately from extrapolation. Missing compressor information can make detailed predictions assumption dominated. |
| Heat-pump dispatch with storage, variable electricity prices and industrial cooling demand | Use detail where it changes dispatch decisions; retain cheap maps in a repeated optimization loop. Sensor coverage can differ substantially between components. | Evaluate realized cost/constraint regret of the chosen schedule under an independent reference, plus total selection and solve time. A small power error can still change a discrete dispatch decision. |
| Heat-exchanger fouling monitoring and cleaning decisions | Separate uncertain operating measurements from gradual changes in effective heat transfer. A performance model adequate for power may be inadequate for diagnosing exchanger deterioration. | Test whether inferred fouling/cleaning decisions remain useful when flow sensors are biased or source conditions change. Ensure the measurement set can distinguish fouling from operating-condition changes. |
| Instrumentation planning and soft sensors | Ask which pressure, temperature or flow measurement makes a desired hidden quantity predictable, rather than measuring all newly introduced states. DM can screen structural insufficiency; numerical sensitivity/uncertainty can rank useful additions. | Compare value per sensor against random/uniform additions for a fixed budget. Structural observability alone does not establish usable accuracy under noise. |
| Gas, water or thermal distribution networks | Select detailed physics only in branches that influence the requested delivery pressure, pumping work or thermal service. Domschke et al. provides a particularly relevant physical-network precedent. | Compare uniform detail with local refinement at equal total cost, including refinement overhead. Gas-network estimators cannot simply be reused for a different fluid/property hierarchy. |
| Commissioning a coupled heat-pump/recycle flowsheet | Use a simpler representation to establish consistent external conditions, reconstruct internal states, and introduce detailed coupling using native initialization routines. | Establish a difficult but realistic case first; compare final-system success and total effort against sound direct initialization. Aggregate feasibility does not establish detailed feasibility. |
| Building thermal models for control or forecasting | Match a thermal-network representation to the data, requested horizon and output; later combine building and heat-pump hierarchies. | Use Bacher–Madsen forward selection as a comparator. This extends the current steady-state scope and should follow the bounded heat-pump experiment. |

Two directly relevant heat-pump application papers make the dispatch and monitoring cases more concrete:

- **Aguilera et al. (2024), “Real-time monitoring and optimization of a large-scale heat pump prone to fouling – towards a digital twin framework,”** DOI [10.1016/j.apenergy.2024.123274](https://doi.org/10.1016/j.apenergy.2024.123274). **Read in companion pass:** abstract and indexed method excerpts; full-text retrieval was blocked. [Aguilera's DTU thesis](https://backend.orbit.dtu.dk/ws/portalfiles/portal/390125828/PhD_Thesis_Jose_Joaquin_Aguilera_Prado.pdf) is a full-text location lead. Use it as an industrial monitoring lead rather than evidence for the proposed selector.
- **Aguilera et al. (2024), “Operation optimization in large-scale heat pump systems: A scheduling framework integrating digital twin modelling, demand forecasting, and MILP,”** DOI [10.1016/j.apenergy.2024.124259](https://doi.org/10.1016/j.apenergy.2024.124259); [author full text](https://digitaltwins4hprs.dk/media/1205/milp.pdf). **Read in companion pass:** Sections 2.2–2.3 and 3.2. Calibrated simulation produces COP maps for MILP scheduling of two heat pumps, storage and a cooling tower. Map discretization trades computational burden against accuracy. Monitoring covers some components while others rely on design information. The evaluated optimized schedules should not be described as deployed closed-loop operation; the paper states the underlying data cannot be shared. [Source](https://digitaltwins4hprs.dk/media/1205/milp.pdf)

## Defensible research questions and gaps

The inspected literature does not establish that the exact combination below has already been solved, but this search is insufficient to establish novelty. A stronger related-work search should target equation-oriented model libraries, automatic problem specification and model-based experimental design before making a publication claim.

1. **Specification quality beyond structural completion.** Under fixed equations, does trust-ranked admissible specification produce better target predictions or fewer weak assumptions than manual, declared-input and random admissible policies? The contribution needs a measured outcome, not just calling DM repeatedly.
2. **Joint information and physical-model decisions.** Does opening a branch help after accounting for its new specifications, calibration requirements and uncertainty? Compare selection of representations with selection of estimated parameters inside a detailed model.
3. **Target dependence with the same data.** Is the best supported implementation different for power prediction, compressor efficiency estimation and condenser duty/sizing? This would connect goal-oriented adaptivity to data-supported selection particularly clearly.
4. **Topology-changing refinement.** Can an aggregate device be expanded into an internal recycle while preserving external physical meaning and a transparent specification contract? Evaluate the extra state reconstruction assumptions explicitly.
5. **Purpose-specific fallback.** Can a simpler valve or inactive-component representation preserve decision usefulness when a detailed constitutive model is outside its admissible domain? This is a changed model with a bounded purpose, not successful initialization or validation of the failed detailed model.

## Recommended experiments, in order

### A. Fixed-implementation specification first

Use a small heat-pump case with genuinely alternative independent specification sets. Freeze relationships, solver, initialization and information records. Compare trust-ranked DM, a manual specification, declared-input selection and random structurally admissible ordering; enumerate small admissible sets offline. Vary missing records, misleading high-trust records, ties and measurement location. Report completion, assumptions selected, numerical success, conditioning and held-out target error separately.

This tests the existing implemented policy without attributing its behavior to future fidelity selection. Include a numerically singular but structurally matched case so matching is not accidentally evaluated as a solvability guarantee.

### B. Small, exhaustively evaluable power hierarchy

Choose perhaps an aggregate COP relation, an explicit cycle with fixed efficiency, and a cycle with a compressor map; include exchanger refinement only if it supplies a meaningful additional distinction. Declare all independently known parameters and calibration requirements. Hold available information fixed. Compare aggregate-only, detailed admissible, greedy refinement and exhaustive offline candidate selection.

Use separate calibration, selector-development and final evaluation operating points. Reserve electrical power used for final evaluation from both specifications and starting guesses. If selection uses validation errors, include that data and fitting cost in its budget. Report a Pareto comparison of error, parameters, assumptions and time before adding an explicit accuracy threshold: the present quantity-of-interest document has no tolerance field.

Include parameter-subset selection within the detailed model to test whether representation selection adds value beyond avoiding overfitting. Test more than one data-generating formulation; synthetic data from the candidate detailed model alone gives that model a privileged position.

### C. Noisy-data extension and target uncertainty

Introduce known correlated noise and bias in controlled cases. Compare fixed central-value specifications with constrained weighted estimation using declared covariance assumptions. Examine target uncertainty as well as parameter uncertainty. Add independent real measurements when a suitable open dataset is found; the industrial scheduling paper's private dataset cannot be assumed available.

### D. Change the question, then investigate initialization

With the same candidate library and data, change the target from power to a component-level quantity. Test whether the useful implementation changes and whether the selector can abstain when no candidate supports the answer.

Study initialization separately only after a realistic coupled case remains difficult with valid starting values and established unit routines. Compare bottom-up DM temporary fixing and aggregate-first transfer against block decomposition/continuation where available. Require identical final equations and operating specifications for initialization comparisons; record failed attempts and temporary-fix restoration. Evaluate deliberate fallback as a separate modeling experiment.

## Reading priorities

1. Read Domschke et al. and Bacher–Madsen in detail before defining refinement or stopping rules.
2. Obtain/read Liu–Cai and the desired-operating-condition ACS paper in full before implementing a new information-support score.
3. Read Parker et al. alongside actual Pyomo incidence behavior and Mitsas before claiming benefits from Jacobian-guided specification replacement.
4. Use the Aguilera application studies to define realistic engineering outputs and data limitations; seek an independently accessible heat-pump dataset.
5. Return to Oden's goal-error machinery and the homotopy literature when target-sensitive estimators or initialization become the active experiment.

## Methods worth borrowing: comparison with this repository

Added after the initial review to emphasize transferable mechanisms. The adaptations below are proposals, not implemented capabilities or reported results. The current `select_specification()` selects independent hard fixations using trust-ranked structural trials; the research notes propose fidelity selection but do not yet establish a target-error estimator or statistical stopping rule.

### Compare possible upgrades, rather than follow a predetermined expansion order

**Borrow from Domschke et al., Sections 2–3:** explicit comparison of local refinement actions, including estimated error reduction and cost. Their realistic-network results also show that the cost-aware strategy did not outperform maximal-error refinement in CPU time. [Full text](https://arxiv.org/html/1701.09031)

**Adaptation here:** generate a small set of one-branch changes from the current heat-pump implementation: for example, compressor-map refinement versus exchanger refinement. Check information support with the same specification policy, then compare useful predictive improvement and total fitting/planning/solve cost. For an initial experiment, measure the candidate benefits directly on development data; later investigate a cheaper estimator. Keep final evaluation data separate. The point is to learn which change is useful, rather than assume that a deeper branch is always the next useful step.

**Small test:** compare fixed expansion order, greatest observed improvement and improvement per measured cost against exhaustive candidate evaluation. Count unsuccessful trials. Include pairs of upgrades in the offline benchmark to expose interactions that one-step greedy search misses.

### Give model expansion an evidence-based stopping rule

**Borrow from Bacher–Madsen, Sections 3.2–4:** compare minimal extensions, stop when none is sufficiently supported, and examine residuals and physical plausibility alongside fit. [Full text](https://henrikmadsen.org/wp-content/uploads/2014/05/Journal_article_-_2011_-_Identifying_suitable_models_for_the_heat_dynamics_of_buildings.pdf)

**Adaptation here:** keep two explicit tests: whether information can structurally specify a candidate, and whether its extra complexity improves the requested prediction. Passing the first should not force expansion. Use an engineering tolerance or a development-data selection rule whose assumptions are declared. Do not directly apply their likelihood-ratio test to arbitrary nonnested COP-versus-cycle formulations.

**Small test:** vary measurement noise and operating-point coverage independently. Ask whether expansion stops earlier with weak data and resumes when informative operating points are added. This tests information content rather than merely counting sensors or records.

### Retain detailed physics while estimating fewer parameters

**Borrow from Liu–Cai:** sensitivity and parameter-dependence screening within a component model; the accessible publisher description supports this mechanism, while the full manuscript remains an access gap. [Publisher](https://www.sciencedirect.com/science/article/abs/pii/S0140700721001705)

**Adaptation here:** introduce a second decision alongside relationship selection: which parameters are independently known, fixed by explicit assumptions, or estimated from calibration data? A detailed cycle could remain useful with only one fitted compressor parameter, without attempting to identify every exchanger and valve coefficient. Fixing parameters adds assumptions; record their uncertainty and test sensitivity rather than treating them as known truth.

**Small test:** compare aggregate COP, a detailed cycle with all eligible parameters estimated, and the same cycle with a screened parameter subset. This reveals whether any advantage comes from selecting physics or simply reducing estimation freedom. It requires a calibration layer beyond the existing structural specification selector.

### Assess whether the requested prediction is constrained, even when parameters are not

**Borrow from Kreutz–Raue–Timmer:** prediction profile likelihood, described in Section V.1. [Full text](https://arxiv.org/html/1107.0013)

**Adaptation here:** at a chosen operating condition, constrain predicted power to successive trial values and refit the uncertain parameters to calibration observations. Examine how much the fit deteriorates. Repeat for a component quantity such as compressor efficiency. A narrow supported range for power and a broad range for efficiency would directly illustrate why the same model and data can answer one question better than another.

**Small test:** construct a controlled case with confounded component parameters and compare target ranges with simulation truth. This requires a likelihood/noise model, repeated constrained optimization and coverage checks; it is a later uncertainty experiment, not a property established by DM matching. Intervals remain conditional on the selected equations and error assumptions.

### Preserve detailed topology but temporarily weaken difficult coupling

**Borrow from De Pascali–Casella, Sections 3 and 5.1:** their homotopy decoupler initially supplies nominal enthalpy/composition while preserving pressure and flow connections, then restores the physical connection. [Full text](https://arxiv.org/html/2411.12666)

**Adaptation here:** compare aggregate-first initialization with a detailed model whose troublesome recycle enthalpy connection is temporarily replaced by `h_out = (1 - lambda) * h_nominal + lambda * h_in`. Continue from zero to one, returning to the exact intended equations and specifications. This offers a different lever from representation expansion: change coupling strength while retaining detailed topology. Choose the connection using numerical coupling evidence, not the semantic tree alone.

**Small test:** compare direct detailed initialization, connection continuation and aggregate-first transfer with identical final conditions. Measure total effort and final residuals, including failures. Nominal states must be physically credible; continuation can encounter singularities. Pyomo will not automatically reproduce Modelica's structural decomposition at the simplified endpoint.

### Suggested order of adoption

Start with the upgrade-comparison experiment and an explicit stopping rule on the small existing heat-pump hierarchy. Add parameter-subset selection as a comparator before attributing a result to fidelity selection. Prediction profiling is especially valuable as a diagnostic study once noisy-data estimation exists. These mechanisms address distinct questions: which change helps, whether to make it, what to calibrate, and how confidently the requested output can be predicted.
