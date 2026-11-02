# Standard symbolic models

The model library includes reusable Helmholtz and humid-air wrappers, an extracted
EN 12900 compressor performance map, and a JSON compressor composition. Register
their providers explicitly before building:

```python
from multifidelity.model_language import (
    Library, build_model, register_standard_providers, required_inputs,
)

library = Library()
register_standard_providers(library)
selection = "examples/model_language/mapped_propane_compressor.json"
model = build_model("mapped_propane_compressor", selection, library=library)
inputs = required_inputs("mapped_propane_compressor", selection, library=library)
```

Registration only associates names with functions. Providers load their native
packages or catalogue when selected for construction. Inspection and required-input
discovery work without registration or compiled thermodynamic functions.
No provider initializes or solves the model. Public variables start free and
without values; wrapped packages may supply their own internal initial guesses.

All bundled public operating fields are time-indexed, including property and
map outputs. The default steady build has one point, so access values with
`variable[0]`. The same selections also build in dynamic context:

```python
model = build_model(
    "mapped_propane_compressor", selection, library=library,
    mode="dynamic", domain_values={"time": [0, 60]},
)
compressor = model.fs.root.relationship.models.compressor
compressor.structs.inlet.pressure[0].set_value(300000)
```

These models remain instantaneous algebraic components. The backend creates
fresh scalar provider state at each time point, and creates new slices when DAE
discretization inserts points. For an external relationship, the native block is
`occurrence.relationship.slices[t].provider`, with public bindings at
`occurrence.relationship.slices[t].bindings`. Direct calls to the Python provider
functions still return scalar mappings as before.

The command-line interface supports the same providers:

```bash
# Inspect four required operating quantities, without constructing native objects.
.venv/bin/python -m multifidelity.model_language mapped_propane_compressor \
  examples/model_language/mapped_propane_compressor.json --required-inputs

# Construct and print the complete model. Requires the Helmholtz extensions.
.venv/bin/python -m multifidelity.model_language mapped_propane_compressor \
  examples/model_language/mapped_propane_compressor.json --standard-providers

# Construct only the extracted map; no thermodynamic package is needed.
.venv/bin/python -m multifidelity.model_language en12900_compressor_map \
  examples/model_language/en12900_compressor_map.json --standard-providers
```

## Available definitions

| Model ID | Relationship | Provider or composition |
| --- | --- | --- |
| `helmholtz_water_ph` | `helmholtz` | `standard.helmholtz_ph`, water, liquid-phase viscosity |
| `helmholtz_propane_ph` | `helmholtz` | `standard.helmholtz_ph`, propane, vapour-phase viscosity |
| `humid_air_state` | `pysmo` | `standard.humid_air`, existing Ahuora PySMO artifact |
| `en12900_compressor_map` | `cooling_60rps` | `standard.en12900_map`, default propane cooling map |
| `mapped_compressor` | `mapped` | Generic JSON composition of property models and a map |
| `mapped_propane_compressor` | `evaluate` | Concrete wrapper supplying propane properties and map |
| `helmholtz_water_property_pair` | `evaluate` | Existing narrow property-pair interface with richer properties |

Each concrete model has an implementation document in `examples/model_language/`.
Use the [custom-model guide](custom-models.md) to add providers or other configured
definitions. `Library(custom_directory)` continues to load only that directory;
provider registration does not insert model definitions.

## Helmholtz pressure–enthalpy state

The provider wraps Ahuora's `HelmholtzExtendedParameterBlock` in mass-basis PH
form. It uses IDAES's registered pure-fluid data without changing the global data
directory through Ahuora's compound-registration helper. This avoids changing
property data for other models in the process.

Inputs are `state.pressure` in Pa and `state.enthalpy` in J/kg. Outputs on
`properties` are:

| Field | Unit |
| --- | --- |
| `temperature` | K |
| `density` | kg/m³ |
| `heat_capacity` | J/(kg K) |
| `viscosity` | Pa s |
| `entropy` | J/(kg K) |
| `vapor_fraction` | dimensionless |
| `temperature_bubble` | K |
| `temperature_dew` | K |

Configure the provider through ordinary JSON values:

```json
"config": {"fluid": "propane", "viscosity_phase": "Vap"}
```

Defaults are `fluid: "h2o"` and `viscosity_phase: "Liq"`. Available fluids depend
on the installed IDAES data. Viscosity is the selected phase's viscosity, not an
effective two-phase mixing rule. Bubble/dew temperatures coincide for pure fluids
and depend only on pressure; use saturation outputs in the subcritical region.
The provider retains Ahuora's small enthalpy-dependent smoothing of reported
temperature. That can slightly change superheat compared with the unsmoothed EOS
temperature.

Native state flow is closed with an internal equality of 1 kg/s because these are
intensive property calculations, not stream-flow models. Outputs represented by
native expressions use scalar bridge variables and equalities. No operating
variable is fixed during construction.

This wrapper needs `ahuora-compounds` and IDAES Helmholtz compiled extensions.
They are already used elsewhere in this project; the feature does not download
or install them. The dependency declarations and JSON definitions can be read
without the compiled extensions.

## Humid-air surrogate

The provider wraps Ahuora's existing `HAirParameterBlock` and its packaged
`pysmo_humid_air.json` artifact. It does not train a new surrogate.

Public inputs are:

- `state.temperature`: dry-bulb temperature in K.
- `state.pressure`: absolute pressure in Pa.
- `state.water_mole_fraction`: dimensionless; air fraction is its complement.

Outputs on `properties` are `relative_humidity`, `temperature_wet_bulb` (K),
`enthalpy` (J/mol), `entropy` (J/(mol K)), and `molar_volume` (m³/mol).
These enthalpy and entropy outputs are **molar**, unlike the Helmholtz PH interface.
They are not interchangeable generic arguments without a suitable adapter.

The native artifact evaluates polynomial equations on numerical SI coordinates.
The provider rebuilds that same loaded surrogate on dimensionless coordinate
variables and links them to the unit-bearing native state variables. This keeps
the polynomial predictions unchanged while satisfying Pyomo's unit checks.
The original surrogate equations are removed, so only one formulation is active.
The native composition-sum equation and an internal 1 mol/s flow equality close
the state, leaving exactly three operating inputs.

This wrapper preserves the existing artifact's behaviour and validity limits;
it does not establish new training-domain or prediction-accuracy claims.

## Extracted compressor map

`standard.en12900_map` contains only the catalogue polynomial equations. It does
not construct a compressor, state blocks, or a property package.

Inputs `temperatures.evaporating` and `temperatures.condensing` are dew-point
temperatures in K. The provider converts them to numerical degrees Celsius and
evaluates the source's ten-term basis:

```text
1, ET, CT, ET², ET·CT, CT², ET³, ET²·CT, ET·CT², CT³
```

Outputs are `performance.mass_flow` (kg/s), `electrical_power` (W), `capacity`
(W), `current` (A), and `rated_cop`. `rating.superheat` and `rating.subcooling`
return the map's fixed rating values in K. Native mass flow in kg/hour is converted
to kg/s. The provider defines rated COP through `COP × electrical_power = capacity`.

Configuration selects a map and an exact discrete speed:

```json
"config": {
  "performance_map": "spb172fnkmt_cooling_pcs661ab",
  "speed_rps": 60
}
```

Both bundled families are for propane (R290): cooling
`spb172fnkmt_cooling_pcs661ab` and heating `spb172fnkmt_heating_sci_hpds009a`.
Speeds run from 20 to 120 rps in steps of 10. There is no speed interpolation.
Inspect exact names, coefficients, source provenance, and rating conditions with:

```python
from multifidelity.model_language.standard.compressor_map import get_catalogue

for entry in get_catalogue()["maps"]:
    print(entry["id"], entry["refrigerant"], entry["rating"])
```

The copied catalogue retains Ahuora's source-workbook and download metadata.
It does not include an application envelope; the equations alone do not establish
valid extrapolation limits. No superheat or subcooling correction is applied.
The default cooling map has rated superheat 11.1 K and subcooling 8.4 K.
Rated capacity follows the selected map's heating/cooling convention and is a
diagnostic output, not an extra compressor energy-balance equation.

## JSON compressor composition and generic properties

`mapped_compressor` declares two model parameters:

- `FluidProperties` requires a PH state interface and temperature plus bubble/dew
  temperature outputs.
- `PerformanceMap` requires the temperature inputs, map outputs, and rating outputs
  described above.

The JSON relationship builds inlet and outlet property states, supplies their
dew temperatures to the map, and owns the balances:

```text
outlet pressure = inlet pressure + pressure rise
mass flow = map mass flow
shaft power = motor efficiency × map electrical power
mass flow × outlet enthalpy = mass flow × inlet enthalpy + shaft power
```

It also reports pressure ratio, actual suction superheat, rated superheat and
subcooling, and superheat deviation. These reproduce the corresponding source
compressor equations. The provider keeps the polynomial details; the wrapper
keeps composition and physics visible as JSON.

There are four required operating inputs: inlet pressure, inlet enthalpy,
pressure rise, and motor efficiency. The map **predicts flow**; inlet flow is not
another independent input. It appears as `performance.mass_flow` and
`outlet.flow`. This differs from the existing efficiency-driven compressor's
specification, which takes inlet flow as an input. Connecting a stream with a
known flow requires an enclosing model to impose that characteristic and choose
another quantity to determine; the wrapper does not silently ignore known flow.

The concrete `mapped_propane_compressor` chooses matching propane properties and
a propane map. Generic interface checks establish names and units, not physical
fluid identity or consistent enthalpy reference conventions. When replacing
arguments, keep map refrigerant, property fluid, and reference conventions
consistent. Passing water properties with a propane map is not physically valid.

Saturation outputs are only required where needed. Existing constant-property
water models keep their original interface. `property_pair` now projects its
five required output fields using individual equations, so it accepts richer
models without forcing the public output structs to grow. Whole-struct connections
still require matching fields; their semantics have not changed.
