"""Run with: uv run python examples/water.py (requires IDAES Helmholtz extensions)."""

import json

from idaes.core import FlowsheetBlock
from idaes.core.solvers import get_solver
from pyomo.environ import ConcreteModel, value

from multifidelity import WaterParameterBlock


def run():
    m = ConcreteModel()
    m.fs = FlowsheetBlock(dynamic=False)
    m.fs.water = WaterParameterBlock()
    m.fs.states = m.fs.water.build_state_block([0], defined_state=True)
    state = m.fs.states[0]
    state.flow_mass.fix(1)
    state.temperature.fix(320)
    state.pressure.fix(300000)
    solver = get_solver("ipopt")
    results = []
    for name in ("linear", "helmholtz", "linear"):
        state.select_fidelity(name)
        state.initialize(solver=solver)
        results.append(
            {
                "fidelity": state.active_fidelity,
                "enthalpy_J_per_kg": value(state.enth_mass),
                "entropy_J_per_kg_K": value(state.entr_mass),
                "density_kg_per_m3": value(state.dens_mass),
                "cp_J_per_kg_K": value(state.cp_mass),
            }
        )
    print(json.dumps(results, indent=2))
    return m, results


if __name__ == "__main__":
    run()
