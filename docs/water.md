# Selectable liquid-water properties

The property implementation is separate from the exchanger:

```text
src/multifidelity/
    base.py                       # Generic Fidelity, mixin, temporary fixations
    property_models/
        water.py                  # IDAES parameter and state blocks
        linear.py                 # Constant-cp affine liquid approximation
        helmholtz.py              # IAPWS-95 liquid property equations
examples/water.py
tests/test_water_properties.py
```

Property builders receive the parent `WaterStateData` directly, with concrete
type annotations and type-only imports. They use its public property variables
and access shared constants through `state.params`; no separate reference
container or attribute mapping is needed.

## Public interface

```python
from multifidelity import WaterParameterBlock

m.fs.water = WaterParameterBlock()
m.fs.states = m.fs.water.build_state_block([0], defined_state=True)
state = m.fs.states[0]
state.flow_mass.fix(1)       # kg/s
state.temperature.fix(320)   # K
state.pressure.fix(300000)   # Pa

state.select_fidelity("linear")
state.initialize(solver="ipopt")

state.select_fidelity("helmholtz")
state.initialize(solver="ipopt")
```

Inputs are `flow_mass`, `temperature`, and `pressure`. Outputs are `enth_mass`
(J/kg), `entr_mass` (J/kg/K), `dens_mass` (kg/m³), and `cp_mass` (J/kg/K).
All are state-owned variables shared by the formulations. IDAES phase aliases
and material/enthalpy-flow methods reference those same variables. Each fidelity
adds four defining equations; flow, temperature, and pressure remain independent
state variables. Selection changes no variable values or fixation flags.

Selection is per state: switching one state does not switch other states or
the exchanger's unit-operation fidelity. Package configuration determines which
builders every new state receives; the first builder is selected initially.
Indexed state blocks also provide IDAES `initialize()` / `release_state()`
support, including temporary state fixation and `hold_state=True`.

To use only the approximation without Helmholtz external functions:

```python
from multifidelity import LinearWater, WaterParameterBlock

m.fs.water = WaterParameterBlock(fidelities={"linear": LinearWater()})
```

The default builds both fidelities and therefore requires IDAES's IAPWS-95
external-function library. Linear-only construction does not create IAPWS
parameter blocks or expressions. No new Python dependency is needed.

## Linear approximation

Let ΔT = T − Tref and ΔP = P − Pref. All coefficients are on the water
parameter block, so every state uses the same constants:

```text
cp  = cp_ref
h   = h_ref + cp_ref ΔT + ΔP / rho_ref
s   = s_ref + (cp_ref / Tref) ΔT − (alpha_ref / rho_ref) ΔP
rho = rho_ref (1 − alpha_ref ΔT + beta_ref ΔP)
```

The defaults are cp_ref = 4180 J/(kg K), alpha_ref = 2.57e-4 K⁻¹ and
beta_ref = 4.6e-10 Pa⁻¹. Reference temperature and pressure are 298.15 K and
101325 Pa. Reference h, s, and density are taken from IAPWS-95 at that point
so switching does not introduce an arbitrary enthalpy or entropy datum shift.
If changing the expansion point, update the reference property values together.

Pressure stays an independent state variable. The affine density relation is
equivalently a linear pressure-density relation at fixed temperature. Entropy
is deliberately linearized rather than logarithmic. This is an academic liquid
heat-capacity approximation, not a thermodynamically consistent surrogate.

## Helmholtz formulation and scope

The higher fidelity uses IDAES `HelmholtzThermoExpressions` for liquid IAPWS-95
enthalpy, entropy, density, and heat capacity at the shared temperature and
pressure. No duplicate private state block or linking equations are needed.
Fluid constants are constructed once on the water parameter block when needed.
See the [IDAES expression-writer documentation](https://idaes-pse.readthedocs.io/en/2.8.0/reference_guides/model_libraries/generic/property_models/helmholtz_expressions.html).

Both formulations represent pure H2O in a single liquid phase. Public state
bounds are 273.16–373.15 K and 0.1–5 MPa. Phase selection, boiling, saturation,
and metastability checks are outside scope; Helmholtz uses the liquid branch.

Run `uv run python examples/water.py` to see a linear → Helmholtz → linear
round trip. Integration tests cover constant heat capacity and affine trends,
unchanged external property connections on switching, and energy-conserving
exchanger solves with each property formulation and both unit formulations.
