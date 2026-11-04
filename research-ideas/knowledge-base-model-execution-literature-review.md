# Literature review: querying historical data through executable process models

Reviewed 4 November 2026. This is a focused scoping review, not a systematic review or a claim of novelty. It extends the [existing literature review](literature-review.md) and [information-directed specification plan](information-directed-specification.md) to the proposed connection between a historian, semantic plant information, and model execution.

## Main finding

There is substantial prior art for each major part of the proposal. The closest architectural precedents are **Mortar** for querying a semantic equipment model and historical time series together, **The World Avatar** for knowledge graphs connected to executable agents and alternative scenarios, and **Twin4Build** for translating semantic equipment descriptions into calibrated dynamic simulations. **MauveDB** is an important earlier precedent for treating model-generated answers as database views. Read these before designing a new query language or comprehensive knowledge platform.

The more specific research question is how a requested output, time interval, available evidence, and representation hierarchy jointly determine a sufficient equation model and admissible specifications. The sources inspected here do not establish a complete solution to that combined problem. That is a boundary of this review, not evidence that no such work exists.

## Scope and reading record

Searches targeted primary papers, author/institutional repositories, official standards, and first-party software documentation. Accessible full texts were screened for relevant sections; this was not a line-by-line review of every paper. Abstract-only readings and inaccessible sources are marked below. Publication years come from paper metadata rather than crawler dates. Proposed project applications are interpretations, distinguished from demonstrated capabilities.

The terms require care: a semantic information model describes equipment, quantities, and relationships; a numerical model supplies equations; an information table supplies candidate evidence. Ontological reasoning does not replace solving equations, and an acyclic computation workflow is different from a cyclic equation system.

## Priority reading

| Order | Read | Question it answers |
| --- | --- | --- |
| 1 | Fierro et al., Mortar (2018), Sections 3–4 | How should semantic discovery and historian queries work together? |
| 2 | Akroyd et al., Universal Digital Twin (2021), architecture and scenarios | How can a knowledge graph connect observations, simulation services, and what-if worlds? |
| 3 | Bjørnskov, Jradi and Wetter (2025), automated model generation | How can semantic plant descriptions generate and calibrate executable component models? |
| 4 | Deshpande and Madden, MauveDB (2006), model-based views | What should querying a model-backed database mean? |
| 5 | Bai et al., derived information framework (2024) | How should dependencies, stale results, and recomputation be represented? |
| 6 | Parker et al. (2023) and Pyomo MPC examples | How can time-indexed evidence enter a process model and support repeated forecasts? |
| 7 | Deshpande et al., model-driven acquisition (2004) | How can the requested answer determine which observations are worth obtaining? |

Links and limitations follow. The standards are reference material to consult while specifying the data contract, rather than an instruction to implement every standard.

## Semantic discovery, history, and executable models

### Mortar: the closest historian-query precedent

**Fierro et al. (2018), “Mortar: An Open Testbed for Portable Building Analytics,” BuildSys 2018.** [Author/project-hosted full text](https://brickschema.org/papers/Mortar-BuildSys-2018-Fierro.pdf). **Read:** architecture, application qualification, and data-retrieval sections.

Mortar separates Brick metadata storage from time-series storage and supplies a unified query processor. Semantic queries resolve relevant streams; retrieval specifies time bounds, resolution, aggregation, desired units, and timestamp alignment. Applications follow qualify, fetch, clean, analyze, and aggregate stages. Qualification checks both equipment structure and data availability. [Paper](https://brickschema.org/papers/Mortar-BuildSys-2018-Fierro.pdf)

**Application:** this is a concrete starting point for the proposed evidence resolver. The existing information table can be the output of fetch/clean and the input to specification selection. **Limit:** demonstrated portable analytics are not automatic extraction of a solvable equation subsystem or automatic fidelity selection.

Current Brick documentation explicitly links Points to external time-series identifiers and database references, enabling retrieval without storing every sample in RDF. It does not prescribe all database connection metadata. [Official time-series reference documentation](https://docs.brickschema.org/metadata/timeseries-storage.html)

### The World Avatar: knowledge plus active computations and scenarios

**Akroyd, Mosbach, Bhave and Kraft (2021), “Universal Digital Twin — A Dynamic Knowledge Graph,” Data-Centric Engineering 2, e14.** DOI [10.1017/dce.2021.10](https://doi.org/10.1017/dce.2021.10). **Read:** architecture and base/parallel-world discussion in the [open paper](https://www.cambridge.org/core/journals/data-centric-engineering/article/universal-digital-twin-a-dynamic-knowledge-graph/FD25CDFF886CD2ED33D1FDFC13F6BEAB).

The architecture combines a knowledge graph with computational agents that update data and perform simulations. A base world represents current reality; parallel worlds represent alternative scenarios. Examples span chemistry and cross-domain simulations. This closely matches a knowledge layer with separate executable services and scenario branches. It does not by itself establish target-directed equation slicing or measurement-aware fidelity selection. [Paper](https://doi.org/10.1017/dce.2021.10)

**Application:** examine how computations declare inputs and outputs and how scenario assumptions are kept separate from observations. Evaluate individual mechanisms before adopting the whole platform. The original monorepo now states that core development moved into the **TheWorldAvatar** organisation; use its migration links when assessing current software. [Official repository notice](https://github.com/cambridge-cares/TheWorldAvatar)

### Derived information: results that know what they depend on

**Bai, Lee, Hofmeister, Mosbach, Akroyd and Kraft (2024), “A derived information framework for a dynamic knowledge graph and its application to smart cities,” Future Generation Computer Systems 152, 112–126.** DOI [10.1016/j.future.2023.10.008](https://doi.org/10.1016/j.future.2023.10.008); [author full text](https://api.repository.cam.ac.uk/server/api/core/bitstreams/cd9050e8-d900-4082-9e2d-48ba871d1c08/content). **Read:** framework, agent interaction, and abstract/application passages.

Derivations encode how information is obtained from other information. Synchronous and asynchronous agents populate directed acyclic derivation graphs and propagate updates; a flood-impact case demonstrates keeping derived information current upon access. [Paper](https://doi.org/10.1016/j.future.2023.10.008)

**Application:** a stored COP result should depend on a specific evidence snapshot, model implementation, assumptions, and computation. Changes can mark it stale. **Limit:** the DAG is a dependency graph between computations, not an algorithm for resolving flowsheet recycles. A whole coupled solve can be one derivation node.

### Twin4Build: semantic descriptions translated into simulation

**Bjørnskov and Jradi (2023), “An Ontology-Based Innovative Energy Modeling Framework for Scalable and Adaptable Building Digital Twins,” Energy and Buildings 292, 113146.** DOI [10.1016/j.enbuild.2023.113146](https://doi.org/10.1016/j.enbuild.2023.113146). **Read:** [institutional abstract/metadata](https://portal.findresearcher.sdu.dk/en/publications/an-ontology-based-innovative-energy-modeling-framework-for-scalab/).

The framework links component models using SAREF4BLDG and SAREF4SYST semantics and demonstrates dynamic simulation. The 2023 abstract describes connection to actual sensing equipment as future work, so that paper alone should not be cited as a deployed historian-driven twin. [Institutional record](https://portal.findresearcher.sdu.dk/en/publications/an-ontology-based-innovative-energy-modeling-framework-for-scalab/)

**Bjørnskov, Jradi and Wetter (2025), “Automated model generation and parameter estimation of building energy models using an ontology-based framework,” Energy and Buildings 329, 115228.** DOI [10.1016/j.enbuild.2024.115228](https://doi.org/10.1016/j.enbuild.2024.115228); [open institutional full text](https://escholarship.org/content/qt1471d0vr/qt1471d0vr.pdf). **Read:** abstract, introduction, and model-generation overview.

Semantic descriptions of components and interactions generate a simulation assembled from dynamic component models. Bayesian parameter estimation calibrates a ventilation-system case and assesses predictive intervals. **Application:** compare its semantic-to-simulation mapping and parameter treatment with the current implementation/information separation. **Limit:** this is not evidence of a general query planner for minimal equation subsets. [Paper](https://doi.org/10.1016/j.enbuild.2024.115228)

Current first-party code documentation separates `SemanticModel` and `SimulationModel` behind a `Model` facade, with a translator between them. That separation is useful to inspect in code. [Twin4Build documentation](https://twin4build.readthedocs.io/en/latest/auto/twin4build.model.html)

A follow-on paper, **“Development and demonstration of a digital twin platform leveraging ontologies and data-driven simulation models” (2025)**, demonstrates performance monitoring, continuous forecasting, and operational scenario comparisons in a university classroom. Its architecture connects data processing, a semantic description, a component library, a translator, and simulation. This is particularly close to the proposed live and what-if applications, although it does not establish automatic target-directed subsystem or fidelity selection. [Publisher full text](https://www.tandfonline.com/doi/full/10.1080/19401493.2025.2504005). **Read:** accessible publisher text for Sections 4–5 and 7; an initial direct fetch failed, but a later search returned these sections.

### OntoCAPE: process-engineering vocabulary to inspect

**Morbach, Wiesner and Marquardt (2008), “OntoCAPE 2.0 — A (Re-)usable ontology for Computer-Aided Process Engineering.”** DOI [10.1016/S1570-7946(08)80171-X](https://doi.org/10.1016/S1570-7946(08)80171-X). **Read:** publisher abstract/metadata only.

OntoCAPE is established prior art for formal process-engineering knowledge representation and reuse. **Application:** inspect terminology and separation of process concepts before inventing a plant ontology. **Limit:** the abstract does not establish a historian interface, streaming execution, or the requested planner. Ontology adoption and equation-solving integration are separate decisions. [Publisher record](https://www.sciencedirect.com/science/article/pii/S157079460880171X)

## Querying models and selecting evidence

### MauveDB: model-generated answers as database views

**Deshpande and Madden (2006), “MauveDB: Supporting Model-based User Views in Database Systems,” SIGMOD, 73–84.** [Author project](https://www.cs.umd.edu/~amol/MauveDB/); [author paper](https://www.cs.umd.edu/~amol/papers/sigmod06-mauvedb.pdf); [full-text mirror inspected](https://courses.cs.duke.edu/cps296.1/spring07/papers/sigmod06-DeshpandeMadden-mauvedb.pdf). **Read:** abstract and model-view architecture/materialization discussion.

MauveDB defines model-based views, supports declarative view definitions and SQL queries, and considers strategies for materialization and maintenance as data changes. The prototype supports regression and interpolation. This is direct conceptual precedent for exposing calculated quantities through a query interface. **Application:** distinguish a query that returns existing observations from one that executes or updates a model-derived view. **Limit:** regression/interpolation views do not demonstrate physical DAE flowsheets, independent-specification selection, or dynamic scenario initialization. [Paper](https://www.cs.umd.edu/~amol/papers/sigmod06-mauvedb.pdf)

### Model-driven acquisition: the answer determines useful observations

**Deshpande, Guestrin, Madden, Hellerstein and Hong (2004), “Model-Driven Data Acquisition in Sensor Networks,” VLDB.** [Author full text](https://www.cs.umd.edu/~amol/papers/vldb04.pdf). **Read:** abstract and introductory optimization formulation.

The BBQ approach combines statistical models with sensor acquisition. It selects observations by balancing confidence improvement against acquisition and communication costs. This directly precedes the idea that an engineering query should determine which measurements are useful. **Application:** formulate evidence selection around answer quality and cost rather than fetching all tags. **Limit:** statistical sensor selection is different from closing a physical equation subsystem; DM completeness alone supplies no probabilistic confidence guarantee. [Paper](https://www.cs.umd.edu/~amol/papers/vldb04.pdf)

## Observation and historian standards

| Source | What it supplies | Boundary |
| --- | --- | --- |
| [W3C/OGC SOSA/SSN Recommendation (2017)](https://www.w3.org/TR/vocab-ssn-2017/) | Observation, sensor, observed property, feature of interest, procedure, phenomenon time, result time | Vocabulary rather than storage engine or solver |
| [OGC SensorThings Sensing 1.1 (2021)](https://docs.ogc.org/is/18-088/18-088.html) | Things, Datastreams, Observations and metadata; filtering and an optional MQTT extension for observation creation and update notifications | Observation API rather than flowsheet execution planner |
| [OPC UA Part 11, Historical Access](https://reference.opcfoundation.org/specs/OPC-10000-11/6) | Raw/modified history, processed aggregates, at-time reads, values with timestamps and status | Plant connectivity/history access rather than simulation semantics |

SOSA distinguishes when a result applies to the world from when the observing activity completed; database arrival time is another concern to record explicitly. A current query needs freshness and alignment rules, not merely the latest sample of each tag. [SOSA definitions](https://www.w3.org/TR/vocab-ssn-2017/)

The document titled **“Semantic Sensor Network Ontology — 2023 Edition”** is currently a **26 October 2026 Working Draft** and links to the 2017 document as the latest Recommendation. Do not mistake the edition title for an approved 2023 standard. [Draft status](https://www.w3.org/TR/2026/WD-vocab-ssn-2023-20261026/)

SensorThings Section 14 explicitly connects HTTP-managed observations to MQTT publication and subscription. This is useful prior design for the proposed ingestion path; MQTT support is optional and must be checked in any implementation. [Normative MQTT section](https://docs.ogc.org/is/18-088/18-088.html#sensorthings-sensing-mqtt-extension)

## Numerical execution, estimation, and forecasting

**Parker, Nicholson, Siirola and Biegler (2023), “Model predictive control simulations with block-hierarchical differential-algebraic process models,” Journal of Process Control 132, 103113.** DOI [10.1016/j.jprocont.2023.103113](https://doi.org/10.1016/j.jprocont.2023.103113). **Read:** official Pyomo integration documentation and citation; paper method not independently reviewed here.

Pyomo MPC provides data structures and utilities for dynamic optimization and rolling-horizon applications. Its `DynamicModelInterface` loads scalar/time-series data and extracts and shifts time-indexed model values. That is a directly relevant integration layer for repeated forecasts using process models. It does not provide the surrounding historian or semantic query planner. [MPC documentation](https://pyomo.readthedocs.io/en/stable/explanation/analysis/mpc/), [interface API](https://pyomo.readthedocs.io/en/6.9.1/api/pyomo.contrib.mpc.interfaces.model_interface.DynamicModelInterface.html)

For noisy evidence, distinguish fixing measurements as specifications from estimating states/parameters or reconciling observations subject to balances. IDAES documents a Parmest workflow for reconciliation and parameter estimation. [Official guide](https://idaes-pse.readthedocs.io/en/main/how_to_guides/workflow/data_rec_parmest.html). The CAPRESE MHE documentation still labels that module forthcoming; do not assume a ready-made estimator from the package overview. [MHE page](https://idaes-pse.readthedocs.io/en/stable/explanations/modeling_extensions/caprese/mhe.html)

For target-directed equation extraction, Pyomo's incidence interface exposes DM decomposition and block triangularization. These are structural building blocks, not a complete target planner. Retaining coupled blocks and choosing admissible boundaries remains project work. [Official incidence API](https://pyomo.readthedocs.io/en/stable/explanation/analysis/incidence/interface.html)

**Additional foundations:** Kapteyn, Pretorius and Willcox (2021), [“A probabilistic graphical model foundation for enabling predictive digital twins at scale”](https://doi.org/10.1038/s43588-021-00069-0), provides a state/observation/control/twin-update framework, with an aircraft example rather than process historians. The existing review already covers selective fidelity and goal-oriented modeling; consult it alongside the [Peherstorfer et al. multifidelity survey](https://arxiv.org/abs/1806.10761). Combining evaluations across fidelities is different from selecting a representation for one query. [FMI 3.0.2](https://fmi-standard.org/docs/3.0.2/) is a later interoperability reference if external simulators become necessary; it does not supply the planner or a co-simulation algorithm.

## Implications for this project

These are proposed design consequences, not claims made by every cited paper:

1. **Keep history, semantic context, and execution distinct.** A time-series store can hold samples; metadata identifies equipment, physical quantities, units, applicability, and external stream references. An execution service creates information tables and numerical instances.
2. **Use a typed query document first.** Specify targets, historical interval or forecast horizon, time grid, analysis mode, explicit implementation, evidence policy, and scenario assumptions. MauveDB and Mortar are reasons to settle semantics before inventing syntax.
3. **Make historical modes explicit.** Independent steady solves, one aggregated operating point, dynamic replay, and state estimation answer different questions. A forecast additionally needs a defensible initial state and future input/controller assumptions.
4. **Separate workflows from equation structure.** A derivation graph can connect ingestion, estimation, solve, and publication while a solve node contains a coupled cyclic equation model.
5. **Defer automatic fidelity and subsystem selection until there is a reproducible baseline.** Semantic proximity is not numerical sufficiency. The hard part is selecting equations and boundary evidence that retain meaningful predictions, not merely retrieving nearby tags.

### First experiment

Implement one historical heat-pump COP query against a small existing dataset using an explicitly selected implementation. Resolve stream identifiers from a small semantic mapping, fetch only the declared evidence, align timestamps with documented rules, build information tables, select specifications, solve, and store results with evidence and model identity. Compare against a manually prepared baseline. Include a missing-sensor interval and a stale-sensor interval to expose how evidence policy changes admissible solves.

Then run the same query through a periodic worker fed by MQTT ingestion. Next compare a dynamic replay with a ten-minute forecast from a shared initial state and two explicit valve schedules. Only after those baselines should a planner select smaller subsystems or different representations; evaluate its target error, solve success, data requirements, and computational cost against full selected models.

The research opportunity to test is **whether information-aware selection can answer an engineering query using less model detail and less evidence while retaining a stated level of usefulness**. The infrastructure connects that experiment; it should not become the main research claim by itself.
