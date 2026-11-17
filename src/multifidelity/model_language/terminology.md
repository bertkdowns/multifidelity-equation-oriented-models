# Model-language terminology

This is the authoritative vocabulary for the Python API, JSON schemas, examples
and viewer. Domain roles and portable representations use the same names across
those surfaces. Pydantic and Pyomo/IDAES retain their framework terminology.

| Term | Meaning | Python representation |
| --- | --- | --- |
| Block | A reusable definition of a public variable interface and its available formulations. It has no operating values or selected formulation. | `BlockCatalog` |
| Formulation | One mathematical representation of a block: constraints, connections, derivatives and child-block references, or an external symbolic provider. | `Formulation` |
| Model | A root block with a formulation selected at every participating block occurrence. | A root block ID plus a `ModelCatalog` |
| Model catalog | Portable recursive formulation choices for a separately supplied root block. Its fields are `formulation` and `subblocks`. | `ModelCatalog`, containing `FormulationSelection` entries |
| Numerical instance | The live Pyomo/IDAES equation system constructed for a model. Construction alone neither selects parameter resources nor solves the equations. | Return value of `build_model()` |
| Block library | Available block definitions indexed by block ID, together with registered symbolic builders. | `BlockLibrary` |
| Block view | A navigable definition in a particular generic-argument and hierarchy context. It exposes alternative formulations without selecting one. | `BlockView` and `FormulationView` |
| Block occurrence | One use of a definition at a hierarchy path. Different occurrences create distinct numerical variables. | Context carried by a `BlockView` |
| Block slot | A replaceable generic block argument, constrained by a required public interface. It is not a numerical parameter. | `BlockSlot`; `block_slots` and `block_arguments` |
| Resource | Available evidence about a model variable: an observation, assumption, setpoint, equipment value or reference value. It carries a tag, variable path, values, units, type, trust and optional uncertainty. | `Resource` |
| Resource catalog | Available resources for an operating case. Several resources may describe the same variable; their tags are unique. | `ResourceCatalog` |
| Tag | The sole resource identifier, used unchanged by feeds, lookup, parameter choices and diagnostics. A tag is separate from the model variable path. | `Resource.tag` |
| Feed | An external source that discovers tags and supplies values. A registry materializes those values as fresh resources while retaining the resource metadata. | `Feed[C]`, with `get_config()`, `get_tags()` and `read(tags)` |
| Feed registry | Live feed objects, indexed by their registration names. It discovers tags, routes bulk reads, validates responses and returns a new resource catalog. | `FeedRegistry` |
| Feed description | Portable metadata for one feed: `name`, `provider_type`, discovered `tags` and JSON `config`. Tags are discovery snapshots, not separately configured assignments. | `FeedDescription` |
| Feed catalog | A serializable snapshot describing the feeds in a registry. It contains no executable objects and does not fetch values. | `FeedCatalog` |
| Provider type | A feed's qualified Python class name, recorded for inspection. Loading this string never imports code or creates a feed. | `FeedDescription.provider_type` |
| Config | Settings belonging to a particular feed or symbolic builder. A feed defines its own Pydantic config type and exposes it through `get_config()`; the registry serializes it as JSON. Runtime clients and credentials stay outside exported config. | Feed-specific Pydantic models; symbolic-builder JSON options |
| Symbolic provider | Trusted Python code that constructs the equations of an external formulation. This is distinct from a feed, which fetches operating data. | `SymbolicProvider`; `BlockLibrary.register_provider()` |
| Parameter | A resource chosen to constrain a model variable. The resource supplies the value; the parameter catalog records the choice. This does not create a Pyomo `Param` or a new variable type. | A selected resource tag |
| Parameter catalog | Chosen resource tags in `parameters` and `initial_values`, plus replacements mapping operating parameter tags to canonical input paths. Unselected resources remain available evidence. | `ParameterCatalog` |
| Parameter selection | A parameter catalog together with structural completeness and diagnostic information. Completeness is not numerical convergence. | `ParameterSelection`, returned by `select_parameters()` |
| Canonical input | A public input not supplied by the chosen parent equations, connections or derivatives, relative to a solve scope. | `canonical_inputs()` |
| Variable replacement | A chosen operating parameter occupies a canonical input's slot. That input remains free and its equations remain intact. | `ParameterCatalog.replacements` |
| Initial condition | A parameter applied at the first time point, distinct from an unfixed starting guess. | `ParameterCatalog.initial_values` |
| Starting guess | An unfixed numerical value obtained from a variable default, unused applicable resources or an initialization callback. | `Variable.default`, `apply_starting_values()` |
| Result snapshot | Saved public variable values, coordinates, fixation state and explicit solve status. It may represent a successful, failed or not-yet-solved model. | `ResultsCatalog` |
| Solver result | The solver library's own response to a numerical solve, separate from the exported snapshot. | For example, the return value of `solver.solve(model)` |
| Workspace catalog | A portable case containing `model_catalog`, `resources`, `results` and optionally `feeds`. The root block ID is in the result snapshot. | `WorkspaceCatalog` |
| Catalog | A validated, JSON-serializable aggregate. It may describe one block, a selected model, a collection of resources or a saved case; it does not necessarily mean a list of unused options. | The public `*Catalog` types |

## How the concepts fit together

```text
Block catalog + root block ID + model catalog
    -> selected model -> live numerical instance

Feed config + live feed objects
    -> feed registry -> fresh resource catalog

Numerical instance + resource catalog
    -> parameter selection -> parameter catalog

Numerical instance + applied parameters + numerical solve
    -> result snapshot

Model catalog + resources + results + optional feed catalog
    -> workspace catalog
```

The diagram describes responsibilities. Building a numerical instance before
parameter selection allows structural algorithms to inspect its final grid and
equations. A feed supplies evidence; fetching that evidence does not automatically
make it a parameter. Applying parameters and solving are separate operations.

## Public schemas and names

- Block catalogs use `formulations`, child `blocks`, `block_slots`, and references
  containing `block` or `block_slot`, with optional `block_arguments`.
- Model catalogs use `formulation` and recursive `subblocks`. The root block is
  supplied separately to `build_model(block_id, model_catalog)`.
- Resources use `tag` and `resource_type`; a resource catalog is a JSON array.
- Parameter catalogs use `parameters`, `replacements`, and `initial_values`.
- Result snapshots use `block_id`, `model_catalog` and optional `parameters`.
- Feed descriptions use `provider_type`; registry registration is
  `register_feed(name, feed)`, with tags discovered by `feed.get_tags()`.

These replace the former ModelDocument, ImplementationDocument,
InformationDocument, SpecificationDocument, ResultsDocument and WorkspaceDocument
names and their old schema keys. Old names are not retained as aliases. Bundled
examples are migrated. External saved files must be migrated before loading.

## Migration from the previous schema

Names change, but tags, variable paths and numerical values retain their meaning.
Update external files and Python imports together; there are no compatibility
aliases for the previous public names.

| Previous schema key | Current key / scope |
| --- | --- |
| `relationships` / `relationship` | `formulations` / `formulation` |
| Child `models` / `submodels` | `blocks` / `subblocks` |
| Block reference `model` | `block` |
| `model_parameters` / `model_parameter` | `block_slots` / `block_slot` |
| `model_arguments` | `block_arguments` |
| `implementation` in results/workspaces | `model_catalog` |
| `implementation` in an external-data provider description | `provider_type` |
| `information` / `information_type` | `resources` / `resource_type` |
| `specification` in results / `specifications` in parameter choices | `parameters` in both contexts |
| `providers` in a workspace | `feeds` |
| Root definition `model_id` in a result | `block_id` |

Definition JSON now lives in `model_language/blocks`. The runnable acquisition
example is `examples/feeds/read_inputs.py`; resource and parameter examples live
in `examples/resources` and `examples/parameters`. The Python modules are
`resources`, `parameters`, `model_selection` and `feeds`.
