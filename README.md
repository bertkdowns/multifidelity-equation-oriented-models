# Selectable IDAES heat exchanger

A steady-state unit operation with wrapper-owned public variables and two
mutually exclusive built-in IDAES heat exchanger implementations.

| Wrapper child | Implementation | Thermal model |
| --- | --- | --- |
| `fidelity_1` | Subclass of IDAES `HeatExchanger` | 0D, countercurrent, LMTD |
| `fidelity_2` | Subclass of IDAES `HeatExchanger1D` | 1D, countercurrent, Radau collocation |

Both children exist in memory, but exactly one is active. Their `interface`
blocks contain **all** equations linking their private variables to the public
interface. Inactive children contribute no equations to a normal Pyomo solve.
The `levels` tuple holds references to the two child objects, in that order.

## Run

Tested on Python 3.12, IDAES 2.8.0, Pyomo 6.9.2, and IPOPT 3.13.2.

```bash
python -m pip install -r requirements.txt
idaes get-extensions
python example.py
python -m pytest -q
```

An existing IPOPT installation is also sufficient for this example. IDAES
extensions must match your operating system; use an appropriate `--distro`
option when necessary. The example uses the IDAES benzene/toluene liquid
property package and needs no Helmholtz external functions. Numerical tests
are skipped if IPOPT is unavailable; structural tests still run.

## Use

Place `multifidelity_hx.py` beside your script, or on your Python module path.

```python
from pyomo.environ import ConcreteModel, check_optimal_termination
from idaes.core import FlowsheetBlock
from idaes.core.solvers import get_solver
from idaes.models.properties.activity_coeff_models.BTX_activity_coeff_VLE import BTXParameterBlock
from multifidelity_hx import MultiFidelityHeatExchanger

m = ConcreteModel()
m.fs = FlowsheetBlock(dynamic=False)
m.fs.properties = BTXParameterBlock(valid_phase='Liq', activity_coeff_model='Ideal')
m.fs.hx = MultiFidelityHeatExchanger(
    hot_side_property_package=m.fs.properties,
    cold_side_property_package=m.fs.properties,
    finite_elements=10,
    collocation_points=3,
)
hx = m.fs.hx
hx.area.fix(10)
hx.overall_heat_transfer_coefficient.fix(500)
hx.length.set_value(5)
# Specify inlet variables on hx.hot_side_inlet and hx.cold_side_inlet,
# or connect them to upstream Ports via ordinary Pyomo Arcs.
# See example.py for a complete set of numerical inlet specifications.

solver = get_solver('ipopt')
hx.fidelity_1.activate()  # Automatically deactivates fidelity_2.
hx.initialize(solver='ipopt')
result = solver.solve(m)
assert check_optimal_termination(result)

hx.fidelity_2.activate()  # Automatically deactivates fidelity_1 and seeds 1D.
hx.initialize(solver='ipopt')
result = solver.solve(m)
assert check_optimal_termination(result)

hx.fidelity_1.activate()  # Switch back; ports and process specifications persist.
```

Alternative selectors: `hx.select_fidelity(1)`, `hx.select_fidelity(2)`,
`hx.select_fidelity(hx.levels[1])`, or `hx.levels[1].activate()`.
`hx.active_fidelity` returns the selected block. Deactivating the selected
child directly raises an error; select the other child instead. You may
still deactivate the entire wrapper normally.

Activation selects equations and seeds guesses. It does **not** run a solver
or automatically choose the best fidelity. The example supplies the explicit
0D → 1D → 0D solve sequence; a flowsheet meta-algorithm can use the same API.
Do not recursively activate all descendant blocks, since that defeats the
exclusive selection contract. Make a new solver instance, or rebuild its
model representation, after switching when using a persistent solver interface.

## Public interface and specifications

| Attribute | Ownership and behavior |
| --- | --- |
| `hot_side_inlet`, `hot_side_outlet`, `cold_side_inlet`, `cold_side_outlet` | Stable public Ports referencing independent wrapper-owned Vars |
| `hot_side_inlet_temperature`, etc. | Top-level Vars behind the public Ports; names follow the property-package port members |
| `area` | Public scalar Var, linked to selected child's area |
| `overall_heat_transfer_coefficient[t]` | Public Var, linked to 0D U or uniform 1D U at every spatial point |
| `heat_duty[t]` | Public output Var; positive heat gained by cold stream |
| `length` | Public mutable positive Param, default 5 in hot-side length units; used only by 1D |
| `levels` | Tuple `(fidelity_1, fidelity_2)` |

Area and U defaults are **unfixed initial guesses**, not process specifications.
Fix them on the wrapper for rating mode. The initializer uses their current
values while initializing the child, so other specifications can be imposed
for the final flowsheet solve. It does not attempt to solve arbitrary
alternative specifications during initialization.

Length is deliberately a Param: it remains available in 0D without creating
an unobservable free design variable. In the present steady-state 1D model,
length maps the normalized spatial coordinate into physical length; with total
area and U fixed, it adds no independent pressure-drop or geometry physics.
There are no placeholder output equations and no zero-valued fake profiles.
Spatial profiles exist only on `fidelity_2`.

Use `hx.hot_side_inlet.temperature[0]`, etc. in external constraints, never
private child ports. External connections and specifications then survive
switches. Public variables are copied from the property package's port schema,
including units, bounds, and domains. Links convert compatible units. Property
packages must support both built-in heat exchangers, use Var-based ports,
and expose consistent state-variable/port names for profile interpolation.
Two different hot- and cold-side property packages may be supplied; the example
and numerical tests use the same liquid package on both sides.

## Initialization and failure handling

Selecting a fidelity copies public boundary values and specifications into
private variables. For 1D it also interpolates state-variable guesses between
public inlet and outlet values, respecting countercurrent flow direction.
Derived properties and derivatives are left for IDAES initialization to solve.
Interpolation is a guess, not a thermodynamically reconciled distributed state.

`hx.initialize(...)` temporarily disables the selected child's linking block,
fixes its inlet/area/U values, and calls the built-in initializer. It restores
variable fixation and equation/block activation flags in `finally`, including
when the child initializer raises. On success it updates public outlet/duty
guesses. Public fixation flags and specifications are preserved. Initializer
failure propagates to the caller; no silent model switch occurs.

A caller can catch the failure, select the other fidelity, initialize it and
solve the flowsheet. Failed numerical iterations can leave private variable
guesses changed; selecting a fidelity reseeds its boundary/state guesses.

Use ordinary initialization tolerance (e.g. `1e-6`) and the desired final solve
tolerance separately. During development, IPOPT's MA27 solver hit a workspace
error for one 1D initialization at `tol=1e-8`; initialization at `1e-6` followed
by a final `1e-8` solve passed. No solver-specific options are hidden in the unit.
For a large production flowsheet, supply appropriate scaling and initialization
for its property packages and operating conditions.

## Scope

This is a **steady-state prototype**, without holdup, pressure drop, wall thermal
storage, geometry correlations, or spatially varying U. Dynamic/holdup requests
are rejected. It provides the structural pattern for your multi-fidelity
flowsheet, rather than a calibrated SGHP exchanger. The 1D child resolves
spatial states; switching alone does not introduce new physical correlations.

All selectable equations are nested under their owning fidelity. Merely putting
Pyomo References on the wrapper would expose one child's variables and would
not supply this stable, independently owned public interface. Copying full
public StateBlocks could also introduce duplicate composition closure equations;
this implementation copies just their port-variable schema instead.

## Validation

Five tests cover exclusive activation and zero degrees of freedom, removal of
inactive variables from active equations, unit consistency, independent model
cloning, initialization failure cleanup, the numerical solve round trip with
energy conservation, and an upstream Feed connected by an expanded Arc.

For the ten-element example (100/120 mol/s liquid streams, 370/300 K inlets,
10 m² area, 500 W/m²/K U), the observed results are approximately:

| Selected model | Hot outlet (K) | Cold outlet (K) | Duty (kW) |
| --- | ---: | ---: | ---: |
| 0D | 353.5047 | 315.1922 | 270.7683 |
| 1D | 353.5018 | 315.1948 | 270.8156 |
| Back to 0D | 353.5047 | 315.1922 | 270.7683 |

## Primary references

- [IDAES 2.8.0 0D source and API](https://idaes-pse.readthedocs.io/en/2.8.0/_modules/idaes/models/unit_models/heat_exchanger.html)
- [IDAES 2.8.0 1D source and API](https://idaes-pse.readthedocs.io/en/2.8.0/_modules/idaes/models/unit_models/heat_exchanger_1D.html)
