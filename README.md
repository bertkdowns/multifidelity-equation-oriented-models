# Shared-state heat exchanger

An IDAES unit model with one public physical interface and two selectable
formulations: lumped (0D, smooth LMTD) and distributed (1D, finite volume).
Both use the same public variable objects. Switching requires no copying of
boundary values or linking equations between duplicate variables.

## Run

```bash
uv sync
uv run python examples/heat_exchanger.py
uv run pytest -q
```

Numerical integration tests require IPOPT. An existing IPOPT installation or
IDAES solver extensions (`uv run idaes get-extensions`) can supply it. Tests
skip when IPOPT is unavailable. Dependencies are declared in `pyproject.toml`.

## Use

```python
from multifidelity import HeatExchanger, LumpedHX, DistributedHX

# m.fs is an IDAES FlowsheetBlock; property packages are already constructed.
m.fs.hx = HeatExchanger(
    hot_side_property_package=m.fs.hot_properties,
    cold_side_property_package=m.fs.cold_properties,
    fidelities={
        "lumped": LumpedHX(),
        "distributed": DistributedHX(finite_elements=10),
    },
)
hx = m.fs.hx
hx.area.fix(10)
hx.U.fix(500)
hx.length.fix(5)
# Fix inlet states or connect hx.hot_inlet / hx.cold_inlet to upstream ports.
# See examples/heat_exchanger.py for a complete runnable model.

hx.select_fidelity("lumped")
hx.initialize(solver=solver)
solver.solve(m)

hx.select_fidelity("distributed")
hx.initialize(solver=solver)
solver.solve(m)
```

The default builders are `LumpedHX()` and `DistributedHX(finite_elements=10)`.
The first supplied fidelity is selected initially.

| Public attribute | Meaning |
| --- | --- |
| `hot_inlet`, `hot_outlet`, `cold_inlet`, `cold_outlet` | Stable ports referencing parent-owned state variables |
| `hot_inlet_state`, `hot_outlet_state`, `cold_inlet_state`, `cold_outlet_state` | Parent-owned thermodynamic state blocks, indexed by flowsheet time |
| `area` | Shared heat-transfer area variable |
| `U[t]` | Shared heat-transfer coefficient variable, uniform over the distributed exchanger |
| `length` | Shared length variable; normally fixed, unused by the lumped formulation |
| `heat_duty[t]` | Expression for cold-stream enthalpy gain, positive into the cold stream |
| `fidelities` | Mapping from names to formulation blocks |
| `active_fidelity` | Selected fidelity name |

Public state-variable names depend on the property package. For the liquid BTX
example, ports expose `flow_mol`, `temperature`, `pressure`, and `mole_frac_comp`.
Defaults are initial guesses, not specifications. To specify duty, add an
external constraint on `heat_duty[t]` and release a suitable specification;
expressions cannot be fixed directly.

`select_fidelity(name)` changes activation flags only. It preserves variable
values and fixation flags. Always select through this method; directly
activating child blocks bypasses mutual exclusion. Rebuild persistent solver
representations after changing fidelity.

`initialize(solver=..., optarg=...)` accepts a solver name or solver object. It
temporarily fixes inlet/design values, prepares boundary/private guesses, and
solves the selected formulation. It restores temporary fixations on failure;
failed iterations may change guesses. Initialize upstream equipment first so
connected inlet values are current. Initialization is for the current rating
inputs; arbitrary alternative specifications are left to flowsheet solving.

## Scope and design

See [docs/design.md](docs/design.md) for the agreed principles, ownership,
fidelity-builder interface, and deferred structural diagnosis work.

The implementation is steady state, countercurrent, with uniform U and no
pressure drop, holdup, reactions, or phase equilibrium. The distributed model
uses finite-volume cell balances rather than the former IDAES collocation
implementation. Property packages must supply temperature, pressure, independent
state variables, and material/enthalpy flow terms. Numerical validation uses
single-phase liquid benzene/toluene.

For the example's 370/300 K inlets, 100/120 mol/s flows, 10 m² area and
500 W/m²/K U, the lumped/distributed duties are approximately 270.768/270.815 kW.

The small integration suite checks connected round-trip solves, unchanged public
specifications and values on selection, common DOF, units, energy conservation,
and recovery after actual solver initialization failures.
