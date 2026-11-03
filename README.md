# Multifidelity model language

This repository develops a JSON language for defining reusable process models, selecting their relationships recursively, recording available information, and constructing symbolic IDAES/Pyomo equation hierarchies.

The language is the primary modeling approach in this project. Its terminology and document concepts are defined in the [glossary](src/multifidelity/model_language/terminology.md). The implementation and examples are documented in the [model language guide](src/multifidelity/model_language/README.md).

## Explore the model library

The [model viewer](model-viewer/README.md) browses the JSON definitions in `src/multifidelity/model_language/models`. It shows model structures and relationships without constructing or solving a model.

## Examples

- [`examples/model_language/`](examples/model_language/): reusable model documents and implementation selections.
- [`examples/custom_models/`](examples/custom_models/): custom Python providers integrated with JSON model definitions.
- [`examples/model_language/pipe_lumped.json`](examples/model_language/pipe_lumped.json): a pipe with cylindrical geometry and lumped thermal dynamics.
- [`examples/information/`](examples/information/): information documents and record inspection.
- [`examples/specification/`](examples/specification/): applying operating specifications.
- [`examples/dynamic_tank/`](examples/dynamic_tank/): dynamic model construction and initial conditions.
- [`examples/steam_generating_heat_pump_system/`](examples/steam_generating_heat_pump_system/): one SGHP plant with independently selectable SGHP and PHNIX representations.

## Run

Install dependencies with `uv sync`. Run the model-language test suite with `uv run pytest -q`. For example, inspect required inputs or construct a model from the command line:

```bash
uv run python -m multifidelity.model_language steam_generating_heat_pump_flowsheet examples/model_language/steam_generating_heat_pump_aggregate.json --required-inputs
```

Standard symbolic providers for Helmholtz properties, humid air, and compressor maps are available when registered explicitly. See the guide for their additional requirements and usage.

## Research direction

The [research ideas](research-ideas/README.md) describe future work on information-directed specification and model selection. The repository focuses on readable definitions, explicit terminology, and construction of symbolic models; construction does not imply numerical solution or validation.
