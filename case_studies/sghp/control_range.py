"""Solver-free source-valve admissibility check under the rating specifications."""

import json
from math import log, sqrt

from pyomo.environ import value

from .full_experiments import CASES
from .full_flowsheet import HERE, build_full_flowsheet


def source_control_range():
    report = {
        "method": "No solve: use specified source flow, tank T/P, source pump work "
        "and efficiency, zero other source pressure drops, and EOS density at "
        "pump outlet h = tank h + W/m. Rearrange the detailed equal-percentage "
        "law for opening.",
        "cases": {},
    }
    for case, specifications in CASES.items():
        model = build_full_flowsheet(**specifications)
        fs = model.fs
        valve = fs.source_valve
        pump = fs.source_pump
        flow = value(fs.source_tank.outlet_state[0].flow_mass)
        enthalpy = value(fs.source_tank.outlet_state[0].enth_mass)
        # This disposable diagnostic model is not a trial start or solution.
        pump.outlet_state[0].enth_mass.set_value(enthalpy + value(pump.work[0]) / flow)
        rho_out = value(pump.outlet_state[0].dens_mass)
        rho_in = value(valve.inlet_state[0].dens_mass)
        drop = value(pump.work[0]) * value(pump.efficiency) * rho_out / flow
        opening = 1 + log(flow / (value(valve.Cv) * sqrt(drop * rho_in * 999))) / log(
            value(valve.alpha)
        )
        report["cases"][case] = {
            "flow_kg_s": flow,
            "pressure_drop_Pa": drop,
            "required_detailed_opening": opening,
            "within_opening_bounds": 0 <= opening <= 1,
        }
    return report


if __name__ == "__main__":
    path = HERE / "data" / "full_source_control_range.json"
    path.write_text(json.dumps(source_control_range(), indent=2) + "\n")
    print(path)
