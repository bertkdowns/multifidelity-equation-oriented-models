"""Run with: uv run python examples/heat_exchanger.py."""

import json

from idaes.core import FlowsheetBlock
from idaes.core.solvers import get_solver
from idaes.models.properties.activity_coeff_models.BTX_activity_coeff_VLE import (
    BTXParameterBlock,
)
from pyomo.environ import ConcreteModel, check_optimal_termination, value

from multifidelity import DistributedHX, HeatExchanger, LumpedHX


def build_model(finite_elements=10):
    m = ConcreteModel()
    m.fs = FlowsheetBlock(dynamic=False)
    m.fs.properties = BTXParameterBlock(valid_phase="Liq", activity_coeff_model="Ideal")
    m.fs.hx = HeatExchanger(
        hot_side_property_package=m.fs.properties,
        cold_side_property_package=m.fs.properties,
        fidelities={
            "lumped": LumpedHX(),
            "distributed": DistributedHX(finite_elements),
        },
    )
    hx = m.fs.hx
    hx.area.fix(10)
    hx.U.fix(500)
    hx.length.fix(5)
    for port, flow, temperature in (
        (hx.hot_inlet, 100, 370),
        (hx.cold_inlet, 120, 300),
    ):
        port.flow_mol.fix(flow)
        port.temperature.fix(temperature)
        port.pressure.fix(300000)
        port.mole_frac_comp[0, "benzene"].fix(0.5)
        port.mole_frac_comp[0, "toluene"].fix(0.5)
    return m


def run():
    m = build_model()
    hx = m.fs.hx
    solver = get_solver("ipopt", options={"tol": 1e-8, "max_iter": 500})
    results = []
    for name in ("lumped", "distributed", "lumped"):
        hx.select_fidelity(name)
        hx.initialize(solver=solver)
        result = solver.solve(m)
        if not check_optimal_termination(result):
            raise RuntimeError(f"{name}: {result.solver.termination_condition}")
        results.append(
            {
                "fidelity": hx.active_fidelity,
                "hot_outlet_K": value(hx.hot_outlet.temperature[0]),
                "cold_outlet_K": value(hx.cold_outlet.temperature[0]),
                "heat_duty_W": value(hx.heat_duty[0]),
            }
        )
    print(json.dumps(results, indent=2))
    return m, results


if __name__ == "__main__":
    run()
