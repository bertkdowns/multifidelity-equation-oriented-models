# Model-language terminology

This is the authoritative vocabulary for the Python API, JSON schemas, examples
and viewer. Domain roles and portable representations use the same names across
those surfaces. Pydantic and Pyomo/IDAES retain their framework terminology.

| Term | Meaning | Python representation |
| --- | --- | --- |
| Block | A reusable definition of a public variable interface and its available formulations. It has no operating values or selected formulation. | `BlockDefinition` |
| Formulation | One mathematical representation of a block: constraints, connections, derivatives and child-block references, or an external symbolic provider. | `Formulation` |
| Model | A root block with a formulation selected at every participating block occurrence. | A root block ID plus a `ModelDocument` |
| Model document | Portable recursive formulation choices for a separately supplied root block. Its fields are `formulation` and `subblocks`. | `ModelDocument`, containing `FormulationSelection` entries |
| Numerical instance | The live Pyomo/IDAES equation system constructed for a model. Construction alone neither selects parameter resources nor solves the equations. | Return value of `build_model()` |
| Block registry | Available block definitions indexed by block ID, together with registered symbolic builders and optional initialization and scaling callbacks. | `BlockRegistry` |
| Block view | A navigable definition in a particular generic-argument and hierarchy context. It exposes alternative formulations without selecting one. | `BlockView` and `FormulationView` |
| Block occurrence | One use of a definition at a hierarchy path. Different occurrences create distinct numerical variables. | Context carried by a `BlockView` |
| Block argument | A replaceable generic block argument, constrained by a required public interface. It is not a numerical parameter. | `BlockArgument`; declarations and bindings both use `block_arguments` |
| Resource | Available evidence about a model variable: an observation, assumption, setpoint, equipment value or reference value. It carries a tag, variable path, values, units, type, trust and optional uncertainty. | `Resource` |
| Resource document | Available resources for an operating case. Several resources may describe the same variable; their tags are unique. | `ResourceDocument` |
| Tag | The sole resource identifier, used unchanged by feeds, lookup, parameter choices and diagnostics. A tag is separate from the model variable path. | `Resource.tag` |
| Feed | An external source that discovers tags and supplies values. A runtime collection materializes those values as fresh resources while retaining the resource metadata. | `Feed[C]`, with `get_config()`, `get_tags()` and `read(tags)` |
| Feed registry | Available trusted plugins, indexed by stable plugin names, with their typed config models and factories. Registration does not construct instances. | `FeedRegistry` |
| Feed collection | Configured runtime instances that discover tags, route bulk reads and return fresh resources. | `FeedCollection`, returned by `create_feeds()` |
| Feed description | Configuration for one feed instance: `name`, `provider_type` and JSON `config`. | `FeedDescription` |
| Feed document | A portable artifact containing a `feeds` array of configured instance descriptions. Tags are discovered at runtime. | `FeedDocument` |
| Provider type | A stable plugin name resolved through the application registry during construction. Loading the document never imports code. | `FeedDescription.provider_type` |
| Config | Settings belonging to a particular feed or symbolic builder. A feed defines its own Pydantic config type and exposes it through `get_config()`; the runtime collection serializes it as JSON. Runtime clients and credentials stay outside exported config. | Feed-specific Pydantic models; symbolic-builder JSON options |
| Symbolic provider | Trusted Python code that constructs the equations of an external formulation. This is distinct from a feed, which fetches operating data. | `SymbolicProvider`; `BlockRegistry.register_provider()` |
| Parameter | A resource chosen to constrain a model variable. The resource supplies the value; the parameter document records the choice. This does not create a Pyomo `Param` or a new variable type. | A selected resource tag |
| Parameter document | Chosen resource tags in `parameters` and `initial_values`, plus replacements mapping operating parameter tags to canonical input paths. Unselected resources remain available evidence. | `ParameterDocument` |
| Parameter selection | A parameter document together with structural completeness and diagnostic information. Completeness is not numerical convergence. | `ParameterSelection`, returned by `select_parameters()` |
| Canonical input | A public input not supplied by the chosen parent equations, connections or derivatives, relative to a solve scope. | `canonical_inputs()` |
| Variable replacement | A chosen operating parameter occupies a canonical input's slot. That input remains free and its equations remain intact. | `ParameterDocument.replacements` |
| Initial condition | A parameter applied at the first time point, distinct from an unfixed starting guess. | `ParameterDocument.initial_values` |
| Starting guess | An unfixed numerical value obtained from a variable default, unused applicable resources or an initialization callback. | `Variable.default`, `apply_starting_values()` |
| Result snapshot | Saved public variable values, coordinates, fixation state and explicit solve status. It may represent a successful, failed or not-yet-solved model. | `ResultsDocument` |
| Solver result | The solver library's own response to a numerical solve, separate from the exported snapshot. | For example, the return value of `solver.solve(model)` |
| Workspace document | A portable case containing `model_document`, `resources`, `results` and optionally `feeds`. The root block ID is in the result snapshot. | `WorkspaceDocument` |
| Document | A portable, validated artifact describing resources, parameter choices, feed configuration, model choices, results or a complete workspace. JSON serialization does not make it a collection. | `ModelDocument`, `ResultsDocument`, `WorkspaceDocument`, `FeedDocument`, `ResourceDocument`, `ParameterDocument` |

Registries describe capabilities available to an application. `BlockRegistry`
holds block definitions, symbolic builders and their optional callbacks;
`FeedRegistry` holds feed plugin factories and config models. Documents record
case-specific choices. Neither registry represents a solved numerical instance.

## How the concepts fit together

```text
Block definition + root block ID + model document
    -> selected model -> live numerical instance

Feed registry + feed document
    -> configured feed collection -> fresh resource document

Numerical instance + resource document
    -> parameter selection -> parameter document

Numerical instance + applied parameters + numerical solve
    -> result snapshot

Model document + resources + results + optional feed document
    -> workspace document
```

The diagram describes responsibilities. Building a numerical instance before
parameter selection allows structural algorithms to inspect its final grid and
equations. A feed supplies evidence; fetching that evidence does not automatically
make it a parameter. Applying parameters and solving are separate operations.

## Public schemas and names

- Block definitions use `formulations`, child `blocks`, `block_arguments`, and references
  containing `block` or `block_argument`, with optional `block_arguments`.
- Model documents use `formulation` and recursive `subblocks`. The root block is
  supplied separately to `build_model(block_id, model_document)`.
- Resources use `tag` and `resource_type`; a resource document is a JSON array.
- Parameter documents use `parameters`, `replacements`, and `initial_values`.
- Result snapshots use `block_id`, `model_document` and optional `parameters`.
- Feed descriptions use `provider_type` to select a plugin registered with
  `register(provider_type, feed_class)`. `create_feeds(document)` constructs runtime
  instances, with tags discovered by `feed.get_tags()`.

## Block argument declarations and bindings

A block declares its required arguments in `block_arguments`, mapping each name
to a `BlockArgument` with a required public interface. A concrete block reference
uses its own `block_arguments` mapping to supply block references for those names.
An `ArgumentBlockReference` uses `block_argument` to forward a named argument from
the current context. The containing object distinguishes declarations from supplied
arguments; both use the same argument names.

## Source layout

Block definitions live in `model_language/blocks`. The runnable acquisition example
is `examples/feeds/read_inputs.py`; resource and parameter examples live in
`examples/resources` and `examples/parameters`. The Python modules are
`resources`, `parameters`, `model_selection` and `feeds`.
