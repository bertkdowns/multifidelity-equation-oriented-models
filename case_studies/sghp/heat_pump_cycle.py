"""Isolated n-butane heat pump derived from the captured SGHP cycle.

Run: uv run python -m case_studies.sghp.heat_pump_cycle
The single sink passes through subcooler then condenser, replacing the original
two water loops. No steam, source-reheat, makeup, or circulation equipment is built.
"""

import json

from idaes.core import FlowsheetBlock
from idaes.core.solvers import get_solver
from idaes.core.util.model_statistics import degrees_of_freedom
from pyomo.environ import ConcreteModel, check_optimal_termination, value

from multifidelity import COPHeatPump, CycleHeatPump, HeatPump
from multifidelity.property_models.phase_equilibrium import phase_parameters
from .full_flowsheet import (
    CALIBRATION, PORT_NAMES, properties, scale_model, seed_state, snapshot,
    stream_references,
)

CYCLE_UNITS = {
    1718031: "compressor", 1718033: "condenser", 1718036: "subcooler",
    1718039: "evaporator", 1718078: "ihx", 1718042: "expansion_valve",
}


def build_model(*, cells=4):
    data = snapshot()
    refs = stream_references(data)
    objects = {o["id"]: o for o in data["simulation_objects"]}
    calibration = json.loads(CALIBRATION.read_text())
    if cells != calibration["provenance"]["cells"]:
        raise ValueError("This example uses the saved four-cell calibration")
    m = ConcreteModel()
    m.fs = FlowsheetBlock(dynamic=False)
    m.fs.water = phase_parameters("h2o")
    m.fs.butane = phase_parameters("n-butane")
    m.fs.hp = HeatPump(
        source_property_package=m.fs.water,
        sink_property_package=m.fs.water,
        refrigerant_property_package=m.fs.butane,
        fidelities={"cop": COPHeatPump(), "cycle": CycleHeatPump(cells)},
    )
    hp = m.fs.hp
    cycle = hp.fidelities["cycle"]
    for port in data["ports"]:
        if port["unitOp"] not in CYCLE_UNITS or port["stream"] is None:
            continue
        unit = getattr(cycle, CYCLE_UNITS[port["unitOp"]])
        name = PORT_NAMES.get(port["key"], port["key"])
        seed_state(getattr(unit, name + "_state")[0], refs[port["stream"]])
    # External conditions are held fixed; outlet enthalpies remain predictions.
    for name, sid in (("source_inlet", 1718069), ("source_outlet", 1718041),
                      ("sink_inlet", 1718057), ("sink_outlet", 1718034)):
        state = getattr(hp, name + "_state")[0]
        seed_state(state, refs[sid])
        if name.endswith("inlet"):
            for variable in state.define_state_vars().values():
                variable.fix()
    # Preserve the subcooler's inlet conditions, using its water flow through
    # both sink exchangers. This deliberately differs from the full SGHP case.
    for name in ("condenser", "subcooler", "evaporator", "ihx"):
        hx = getattr(cycle, name)
        hx.area.fix(1)
        hx.length.fix(5)
        hx.U.fix(calibration["exchangers"][name]["UA_W_K"])
        hx.select_fidelity("high")
    cycle.subcooler.hot_pressure_drop.fix(14242)
    cycle.compressor.efficiency.fix(properties(objects[1718031])["efficiency_isentropic"])
    cycle.compressor.outlet_state[0].flow_mass.fix(refs[1718032]["flow_mass"])
    cycle.compressor.outlet_state[0].pressure.fix(refs[1718032]["pressure"])
    cycle.compressor.inlet_state[0].pressure.fix(refs[1718044]["pressure"])
    valve = cycle.expansion_valve
    vcal = calibration["valves"]["expansion_valve"]
    valve.Cv.fix(vcal["Cv"])
    valve.nominal_Cv.set_value(vcal["nominal_Cv"])
    valve.nominal_density.set_value(vcal["density_kg_m3"])
    valve.nominal_pressure_drop.set_value(vcal["pressure_drop_Pa"])
    valve.nominal_opening.set_value(vcal["opening"])
    valve.opening[0].set_value(vcal["opening"])
    valve.select_fidelity("high")
    hp.select_fidelity("cycle")
    scale_model(m)
    return m


def run():
    m = build_model()
    solver = get_solver("ipopt", options={
        "tol": 1e-8, "max_iter": 500, "nlp_scaling_method": "user-scaling",
    })
    m.fs.hp.initialize(solver=solver)
    result = solver.solve(m)
    if not check_optimal_termination(result):
        raise RuntimeError(str(result.solver.termination_condition))
    hp = m.fs.hp
    print(json.dumps({
        "degrees_of_freedom": degrees_of_freedom(m),
        "electrical_power_W": value(hp.electrical_power[0]),
        "heating_duty_W": value(hp.heating_duty[0]),
        "cooling_duty_W": value(hp.cooling_duty[0]),
        "heating_COP": value(hp.heating_duty[0] / hp.electrical_power[0]),
        "ihx_duty_W": value(hp.fidelities["cycle"].ihx.heat_duty[0]),
    }, indent=2))
    return m


if __name__ == "__main__":
    run()
