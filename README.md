# Multi-fidelity process modeling research

This is an academic research project focused on **initialization through
fidelity changes** and **selective flowsheet refinement**. See the
[research purpose](research-ideas/README.md) for its goals and scope priorities.

The [milk evaporator example](case_studies/milk_evaporator/README.md) compares
aggregate balances and heat recovery against an explicit valve/exchanger/
separator/translator/MVR effect using published Ahuora packages.

An IDAES unit model with one public physical interface and two selectable
formulations: lumped (0D, smooth LMTD) and distributed (1D, finite volume).
Both use the same public variable objects. Switching requires no copying of
boundary values or linking equations between duplicate variables.

The package also provides [selectable liquid-water properties](docs/water.md):
a constant-cp linear approximation and liquid IAPWS-95 Helmholtz equations,
using the same fidelity interface and shared state variables.

The [complete SGHP case study](case_studies/sghp/FULL_STUDY.md) reconstructs the
coupled refrigerant, IHX, flash-steam, warm-water, and source circuits. All five
exchangers and four valves have low/high formulations. It compares nine baseline
and selection strategies, including residual- and structure-guided switching.
See its [results](case_studies/sghp/FULL_RESULTS.md).

The earlier [SGHP source-loop case study](case_studies/sghp/README.md) compares direct
nonlinear solving, staged valve initialization, residual-based refinement, and
a basic valve fallback for continued low-flow analysis.
Its [results and conclusions](case_studies/sghp/RESULTS.md) are recorded alongside
the experimental inputs and numerical baseline.

Reusable equipment lives under `src/multifidelity/unit_models/`, with one
subfolder per unit model. Water properties live under `property_models/`;
`base.py` contains fidelity assembly and selection; `workflow.py` contains
flowsheet-level searches and rollback. Case-specific construction, acceptance,
and research policies live under `case_studies/`.

## Run

```bash
uv sync
uv run python examples/heat_exchanger.py
uv run python examples/water.py
uv run python -m case_studies.sghp.experiments
uv run python -m case_studies.sghp.full_experiments
uv run pytest -q
```

Numerical integration tests require IPOPT. An existing IPOPT installation or
IDAES solver extensions (`uv run idaes get-extensions`) can supply it. Tests
skip when IPOPT is unavailable. Dependencies are declared in `pyproject.toml`.
The heat-exchanger example uses linear liquid-water properties and needs no
Helmholtz extensions. `examples/water.py` and Helmholtz-specific tests also need
the IDAES Helmholtz extensions.

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
| `hot_pressure_drop[t]`, `cold_pressure_drop[t]` | Shared pressure-drop variables, fixed to zero by default |
| `fidelities` | Mapping from names to formulation blocks |
| `active_fidelity` | Selected fidelity name |

Public state-variable names depend on the property package. For the liquid-water
example, ports expose `flow_mass`, `temperature`, and `pressure`.
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
fidelity-builder interface, and flowsheet selection workflow.

The implementation is steady state, countercurrent, with uniform U, specified
pressure drops, no holdup, and no reactions. The distributed model
uses finite-volume cell balances rather than the former IDAES collocation
implementation. Property packages must supply temperature, pressure, independent
state variables, and material/enthalpy flow terms. Numerical validation uses
single-phase liquid water and, in the full SGHP study, phase-capable n-butane and
water PH states. `ChenHX` and `SegmentedHX` provide the study's lumped and
mixed-cell alternatives; the original defaults remain available.

For the example's 370/300 K inlets, 1/1.2 kg/s flows, 10 m² area and
500 W/m²/K U, the lumped/distributed duties are approximately 166.682/166.685 kW.

The small integration suite checks connected round-trip solves, unchanged public
specifications and values on selection, common DOF, units, energy conservation,
and recovery after actual solver initialization failures.

## JSON model language

The experimental [JSON model language](src/multifidelity/model_language/README.md)
provides reusable model definitions, recursive relationship selections, and
construction of an IDAES/Pyomo equation hierarchy without solving. Bundled
examples cover the heat pump, SGHP source loop, full SGHP topology, and milk
evaporator. Their simplified equations are construction examples, not numerical
replacements for the existing case studies.
