# How to connect a custom Pyomo or IDAES model

For ready-made providers and their model definitions, see the
[standard symbolic model library](standard-models.md).

A custom model uses the same public structs and implementation selections as a
JSON model. Its selected relationship names a Python provider. The provider builds
symbolic objects and returns a mapping; the framework connects those objects to
the public variables with equality constraints.

The complete runnable example is in
[`examples/custom_models`](../../../examples/custom_models). From the repository root:

```bash
.venv/bin/python examples/custom_models/build.py
```

This constructs a pump and a replaceable liquid-density model. It prints three
required operating inputs and does not call a solver. The example uses illustrative
constant properties, not a validated thermodynamic package.

## 1. Declare the public interface and external relationship

Keep one JSON file per reusable model in a library directory. Public quantities
belong to the model; implementation details belong to its relationships.

For example, a density model can expose one output:

```json
{
  "id": "liquid_density",
  "domains": {"time": {"kind": "time"}},
  "structs": {
    "properties": {
      "direction": "output",
      "variables": {"density": {"unit": "kg/m**3", "dimensions": ["time"]}}
    }
  },
  "relationships": {
    "constant_python": {
      "external": {
        "provider": "example.liquid_density",
        "config": {"density_kg_m3": 997},
        "dependencies": {"properties.density": []}
      }
    }
  }
}
```

`provider` is a stable registered name, not a Python import path. JSON documents
cannot name Python imports; only explicitly registered providers execute.
Application setup registers trusted Python functions.

`config` is an optional dictionary of JSON values: strings, numbers, booleans,
null, lists, and nested objects. It defaults to `{}`. Use it for construction
choices such as coefficients, formulation options, or an artifact identifier.
Operating inputs belong on the public structs, not in configuration. The framework
does not require a configuration schema; providers interpret their own options.
Each construction receives a deep copy so changes cannot leak between occurrences.

`dependencies` lists every public output exactly once. Each value lists public
input paths that can influence that output. An empty list means no public input
dependencies, as for the constant density above. For the example pump:

```json
"dependencies": {
  "performance.work": [
    "inlet.flow",
    "inlet.density",
    "parameters.pressure_rise",
    "parameters.efficiency"
  ]
}
```

These declarations contribute to the existing structural dependency graph and
stand in for JSON `determines` declarations. They are the author's contract: the
framework checks public path names and output coverage, but does not inspect
provider equations to verify the declarations or prove mathematical determinacy.
All public inputs remain required unless supplied by the containing JSON model;
omitting an input from a dependency list does not make that input optional.

A relationship has either an `external` implementation or ordinary JSON children,
constraints, and connections. They cannot be mixed. Other relationships on the
same model can still use JSON equations, sharing the same public structs.

## 2. Write a provider

The provider interface is:

```python
from collections.abc import Mapping
from pydantic import JsonValue
from pyomo.core.base.block import BlockData
from pyomo.core.base.var import VarData

def build_density(
    block: BlockData,
    config: dict[str, JsonValue],
) -> Mapping[str, VarData]:
    ...
```

Annotations are optional. `Provider` in
`multifidelity.model_language.providers` describes the callable type.

An implementation of the density provider is:

```python
from pyomo.environ import Constraint, Var, units

def build_density(block, config):
    block.density = Var(units=units.kg / units.m**3)
    block.constant = Constraint(
        expr=block.density
        == config.get("density_kg_m3", 997) * units.kg / units.m**3
    )
    return {"properties.density": block.density}
```

The framework supplies a fresh attached Pyomo block for each occurrence. Build
all private Pyomo/IDAES objects underneath it. Return exactly one entry for every
declared public variable, including inputs. Values must be scalar Pyomo variables;
an element such as `state[0].temperature` is acceptable, while an entire indexed
variable, an expression, or a number is not.

For time-indexed interfaces, that scalar provider is called separately at each
time point. Each call receives a fresh block and a deep copy of configuration.
Pyomo DAE discretization also constructs slices for newly inserted points. Public
fields may be scalar inputs or indexed by the shared time domain; all outputs of
a time-sliced provider must be time-indexed. Scalar inputs are shared across
slices. Spatial or other multidimensional provider interfaces are not supported.
The backend checks this shape during input discovery as well as construction.

Native blocks and binding lists live at `relationship.slices[t].provider` and
`relationship.slices[t].bindings`. An entirely scalar custom interface still
uses `relationship.provider` and `relationship.bindings`, preserving the original
provider API. Native provider functions themselves always return scalar variables.

The framework creates separate public variables from the manifest and adds
unit-converting equalities to the mapped variables. For example, a public pressure
in Pa can map to a provider variable declared in kPa. The returned dictionary
contains references, not new owners of the internal variables. Internals are not
accessible to the containing JSON relationship.

Providers should construct equations without solving or fixing operating inputs.
Input/output directions do not impose fixed/free solver status. Represent configured
constants with parameters or equations, as above. Correctness of the provider's
physics, equations, and dependency declarations remains its author's responsibility.
Interface mapping checks and Pyomo unit-consistency checks still apply.

For an existing IDAES model, construct the package/model under `block` and return
its scalar variable objects under the public names. If it uses time-indexed state
blocks, select the appropriate scalar state when constructing the mapping. No
special IDAES provider class is required.

If a package exposes a property as an expression or parameter rather than a
variable, create a private scalar `Var`, constrain it equal to that property, and
return the new variable in the mapping.

## 3. Register and build

```python
from multifidelity.model_language import Library, build_model, required_inputs

library = Library("path/to/model_definitions")
library.register_provider("example.liquid_density", build_density)

selection = {

    "relationship": "constant_python"
}

model = build_model("liquid_density", selection, library=library)
inputs = required_inputs("liquid_density", selection, library=library)
```

`Library()` without a directory loads the bundled JSON library. The existing
`library.models` dictionary can also hold additional typed `ModelDocument` definitions.

Registration belongs to that library instance. Duplicate provider names are
rejected. Only providers selected for construction need to be registered: loading
definitions, navigating resolved models, and discovering required inputs do not
call providers. Selecting a JSON alternative does not require its Python alternative's
provider. Construction errors identify the occurrence, relationship, and provider,
and retain the original exception as their cause.

The implementation-document format is unchanged. An external relationship is a
leaf and has no child selections. A provider does not receive public variables,
the library, model parameters, or a helper for building other registered models.

## 4. Compose dependencies with a JSON wrapper

If a Python pump needs density from a property model, expose density as a public
pump input. Put both models inside an ordinary JSON relationship:

```text
JSON pump wrapper
  properties: FluidProperties model parameter
      properties.density -> core.inlet.density
  core: pump_core model, with a Python relationship
```

The wrapper declares `FluidProperties` using the existing `model_parameters`
interface.

The wrapper and its containing model both declare the `time` domain, and the
generic required variables include `"dimensions": ["time"]`, matching the
supplied density model. Bind domains on child occurrences, not on the generic
definition arguments themselves.

A containing model supplies a concrete definition:

```json
"models": {
  "pump": {
    "model": "pump",
    "domain_bindings": {"time": "time"},
    "model_arguments": {
      "FluidProperties": {"model": "liquid_density"}
    }
  }
}
```

The wrapper's relationship declares its children normally:

```json
"models": {
  "properties": {"model_parameter": "FluidProperties", "domain_bindings": {"time": "time"}},
  "core": {"model": "pump_core", "domain_bindings": {"time": "time"}}
}
```

Use a constraint to connect the individual density field, or a connection if the
entire source and destination structs have matching fields:

```json
"constraints": {
  "density": {
    "for_each": {"t": "time"},
    "lhs": "core.inlet.density[t]",
    "rhs": "properties.properties.density[t]",
    "determines": "core.inlet.density[t]"
  }
}
```

The existing implementation document chooses a relationship for each child:

```json
{
  "relationship": "flowsheet",
  "submodels": {
    "pump": {
      "relationship": "composed",
      "submodels": {
        "properties": {
          "relationship": "constant_python"
        },
        "core": {
          "relationship": "python"
        }
      }
    }
  }
}
```

In the runnable example, change `constant_python` to `constant_json` to use JSON
equations for the density model. The pump provider and the wrapper connections
stay the same. Required inputs are only flow, pressure rise, and efficiency:
the wrapper already supplies the pump core's density input.

## OMLT models

An OMLT formulation can be constructed inside a provider using the same interface.
Attach an `OmltBlock` under the supplied block, build its formulation, and map the
network inputs and outputs to named public quantities. The provider owns feature
ordering, scaling, training-domain bounds, and artifact loading. Keep those details
with the provider and its construction configuration.

OMLT variables often use dimensionless numerical coordinates. When public
quantities have physical units, introduce unit-bearing bridge variables rather
than returning expressions in the mapping. For a network input expressed as a
temperature in kelvin, for example:

```python
block.temperature = Var(units=units.K)
block.temperature_link = Constraint(
    expr=block.temperature / units.K == block.nn.inputs[0]
)
# Return block.temperature for the public temperature path.
```

Apply the corresponding treatment to physical outputs. Let OMLT handle its
configured scaling; do not apply it twice. See the
[OMLT quick-start](https://omlt.readthedocs.io/en/stable/quickstart.html) for formulation,
scaling, and input-bound construction. OMLT is optional and is not installed by
this feature; applications register their own providers and install the packages
those providers use.

This support constructs scalar symbolic models and repeats them over time when
requested by the public interface. Numerical Python function evaluation,
initialization, automatic solving, and native spatially indexed provider
interfaces are outside its scope.

## Optional initialisation callback

Register numerical initialisation separately from symbolic construction:

```python
from multifidelity.model_language import (
    apply_specification, apply_starting_values, initialize_custom_models,
)


def initialize_density(block, config):
    if not block.density.fixed:
        block.density.set_value(config.get("density_kg_m3", 997))


library.register_provider(
    "example.liquid_density", build_density, initializer=initialize_density,
)
# After build_model(), and after discretization if series information is used:
apply_specification(model, specification, information)
apply_starting_values(model, information, specification)
initialize_custom_models(model)
```

Callbacks receive the existing native provider block and a fresh copy of its
construction configuration. They can calculate guesses or call a native package
initialiser. They are never invoked during construction or specification.
Callbacks that invoke a solver must check its outcome and raise on failure.

The runner transfers public input guesses to native variables with unit conversion
and temporarily fixes native counterparts of fixed public quantities, including
fixed outputs. After a callback, it copies available native values back to free
public variables. It restores the original variable fixity, fixed values, and
constraint activation statuses; a failed callback also restores that slice's
starting values. Previously completed slices retain their results. Callback
exceptions propagate to the caller. Callbacks must not add/remove components,
change bounds, alter model parameters, or activate/deactivate whole blocks.

Time-indexed providers run once per existing time slice, including slices created
by discretization. Metadata follows model cloning. Providers without callbacks
are left untouched. The runner does not choose temporary free-input fixes or
solve JSON parents. Use `initialize_model()` for the bottom-up DM procedure,
which calls provider hooks at their own stages and then solves JSON parents.
