"""Complete SGHP topology with PH refrigerant/steam and nine fidelity choices.

A research reconstruction, not a replay of Ahuora's measurement-driven controls.
All parameter fitting is explicit in calibrate(); trial construction never solves.
"""

import json
from pathlib import Path

from idaes.core import FlowsheetBlock
from idaes.core.solvers import get_solver
from idaes.core.util.model_statistics import degrees_of_freedom
from pyomo.environ import (
    ConcreteModel,
    Constraint,
    TransformationFactory,
    value,
    units as u,
    check_optimal_termination,
    Suffix,
)
from pyomo.network import Arc
from pyomo.core.expr.visitor import identify_variables

from multifidelity import HeatExchanger, Pump, ThermalConditioner, Valve
from multifidelity.property_models.phase_equilibrium import phase_parameters
from multifidelity.unit_models.compressor import Compressor
from multifidelity.unit_models.mixer import Mixer
from multifidelity.unit_models.splitter import Splitter
from multifidelity.unit_models.flash_separator import FlashSeparator
from multifidelity.unit_models.heat_exchanger.segmented import SegmentedHX
from multifidelity.unit_models.heat_exchanger.chen import ChenHX
from multifidelity.unit_models.valve.pressure_flow import PressureFlowValve
from multifidelity.unit_models.valve.basic import BasicValve
from multifidelity.unit_models.valve.vapor import VaporPressureFlowValve
from multifidelity.unit_models.streams import interpolate

HERE = Path(__file__).parent
CALIBRATION = HERE / "data" / "full_calibration.json"
HX_NAMES = {
    1718033: "condenser",
    1718036: "subcooler",
    1718039: "evaporator",
    1718058: "cooling_exchanger",
    1718078: "ihx",
}
VALVE_NAMES = {
    1718042: "expansion_valve",
    1718052: "hot_water_valve",
    1718054: "steam_valve",
    1718089: "source_valve",
}
UNIT_NAMES = (
    HX_NAMES
    | VALVE_NAMES
    | {
        1718031: "compressor",
        1718045: "flash",
        1718048: "hot_water_pump",
        1718050: "hot_water_mixer",
        1718056: "warm_water_pump",
        1718062: "splitter",
        1718065: "warm_water_mixer",
        1718068: "source_pump",
        1718070: "source_heater",
        1718072: "source_tank",
    }
)
PORT_NAMES = {
    "hotInlet": "hot_inlet",
    "hotOutlet": "hot_outlet",
    "coldInlet": "cold_inlet",
    "coldOutlet": "cold_outlet",
}


def snapshot():
    return json.loads((HERE / "data" / "full_flowsheet_snapshot.json").read_text())


def properties(obj):
    return {
        p["key"]: p["values"][0]["value"]
        for p in obj["property_set"]["ContainedProperties"]
        if p["values"]
    }


def stream_references(data):
    refs = {}
    for obj in data["simulation_objects"]:
        if obj["objectType"] != "stream":
            continue
        p = properties(obj)
        refs[obj["id"]] = {
            "name": obj["componentName"],
            "component": obj["selected_compounds"][0],
            "flow_mass": p["flow_mass"],
            "temperature": p["temperature"] + 273.15,
            "pressure": p["pressure"] * 1000,
            "vapor_frac": p["vapor_frac"],
        }
    return refs


def port_name(unit_id, port):
    key = port["key"]
    if unit_id in {1718050, 1718065} and key == "inlet":
        return ("main", "makeup")[port["index"]]
    if unit_id == 1718045 and key == "outlet":
        return ("liquid", "vapor")[port["index"]]
    if unit_id == 1718062 and key == "outlet":
        return ("main", "branch")[port["index"]]
    return PORT_NAMES.get(key, key)


def seed_state(state, ref, flow_factor=1):
    state.flow_mass.set_value(ref["flow_mass"] * flow_factor)
    state.pressure.set_value(ref["pressure"])
    inputs = {"p": ref["pressure"] * u.Pa}
    if 0 < ref["vapor_frac"] < 1:
        inputs["x"] = ref["vapor_frac"]
    else:
        inputs["T"] = ref["temperature"] * u.K
    state.enth_mass.set_value(state.params.htpx(**inputs))


def seed_exchangers(model):
    for name in HX_NAMES.values():
        hx = getattr(model.fs, name)
        b = hx.fidelities["high"]
        n = len(b.cells)
        for x in b.interior:
            interpolate(
                b.hot_states[0, x], hx.hot_inlet_state[0], hx.hot_outlet_state[0], x / n
            )
            interpolate(
                b.cold_states[0, x],
                hx.cold_outlet_state[0],
                hx.cold_inlet_state[0],
                x / n,
            )
        for x in b.cells:
            b.cell_duty[0, x].set_value(value(hx.heat_duty[0]) / n)


def scale_model(model):
    """Unit-based residual/variable scales, identical across strategies."""
    if not hasattr(model, "scaling_factor"):
        model.scaling_factor = Suffix(direction=Suffix.EXPORT)

    def scale(component):
        unit = str(u.get_units(component))
        return {
            "Pa": 1e-5,
            "J/kg": 1e-5,
            "W": 1e-4,
            "J/s": 1e-4,
            "kg/s": 1,
            "K": 1e-2,
            "W/K/m**2": 1e-2,
            "m**3/Pa**0.5/s": 1e4,
        }.get(unit, 1)

    model.scaling_factor.clear()
    for c in model.component_data_objects(Constraint, active=True):
        model.scaling_factor[c] = scale(c.body)
        for v in identify_variables(c.body, include_fixed=False):
            model.scaling_factor[v] = scale(v)


def build_full_flowsheet(
    *, load=1.0, source_flow_factor=None, cells=4, calibration_path=CALIBRATION
):
    data = snapshot()
    refs = stream_references(data)
    objects = {o["id"]: o for o in data["simulation_objects"]}
    cal = (
        json.loads(Path(calibration_path).read_text())
        if calibration_path is not None
        else None
    )
    m = ConcreteModel()
    m.fs = FlowsheetBlock(dynamic=False)
    fs = m.fs
    fs.water = phase_parameters("h2o")
    fs.refrigerant = phase_parameters("n-butane")
    packages = {"water": fs.water, "n-butane": fs.refrigerant}
    by_unit = {}
    for p in data["ports"]:
        if p["stream"] is not None:
            by_unit.setdefault(p["unitOp"], []).append(p)
    for uid, name in UNIT_NAMES.items():
        ports = by_unit[uid]
        package = packages[refs[ports[0]["stream"]]["component"]]
        if uid in HX_NAMES:
            pkgs = {p["key"]: packages[refs[p["stream"]]["component"]] for p in ports}
            unit = HeatExchanger(
                hot_side_property_package=pkgs["hotInlet"],
                cold_side_property_package=pkgs["coldInlet"],
                fidelities={"low": ChenHX(), "high": SegmentedHX(cells)},
            )
        elif uid in VALVE_NAMES:
            builders = {"low": BasicValve(), "high": PressureFlowValve()}
            if name == "steam_valve":
                pin = refs[1718047]
                pout = refs[1718055]
                builders["high"] = VaporPressureFlowValve(
                    inlet_pressure=pin["pressure"],
                    outlet_pressure=pout["pressure"],
                    temperature=pin["temperature"],
                )
            unit = Valve(
                property_package=package,
                fidelities=builders,
                characteristic="equal_percentage"
                if name == "source_valve"
                else "linear",
            )
        else:
            cls = {
                "compressor": Compressor,
                "phaseSeparator": FlashSeparator,
                "mixer": Mixer,
                "splitter": Splitter,
                "pump": Pump,
                "heater": ThermalConditioner,
                "cooler": ThermalConditioner,
            }[objects[uid]["objectType"]]
            unit = cls(property_package=package)
        fs.add_component(name, unit)
    producers = {}
    consumers = {}
    fs.stream_states = {}
    fs.stream_ports = {}
    for uid, ports in by_unit.items():
        if uid not in UNIT_NAMES:
            continue
        unit = getattr(fs, UNIT_NAMES[uid])
        for p in ports:
            name = port_name(uid, p)
            state = getattr(unit, name + "_state")[0]
            sid = p["stream"]
            seed_state(state, refs[sid], load)
            fs.stream_states.setdefault(sid, []).append(state)
            fs.stream_ports.setdefault(sid, []).append(getattr(unit, name))
            (producers if p["direction"] == "outlet" else consumers).setdefault(
                sid, []
            ).append(getattr(unit, name))
    for sid, outs in producers.items():
        for i, inp in enumerate(consumers.get(sid, [])):
            fs.add_component(f"stream_{sid}_{i}", Arc(source=outs[0], destination=inp))
    TransformationFactory("network.expand_arcs").apply_to(m)
    for uid, name in HX_NAMES.items():
        hx = getattr(fs, name)
        p = properties(objects[uid])
        hx.area.fix(1)
        hx.length.fix(5)
        hx.U.fix(cal["exchangers"][name]["UA_W_K"] if cal else 1000)
        for side in ("hot", "cold"):
            key = f"{side}_side.deltaP_inverted"
            prop = next(
                p
                for p in objects[uid]["property_set"]["ContainedProperties"]
                if p["key"] == key
            )
            dp = p[key] * (1000 if prop["unit"] == "kPa" else 1)
            getattr(hx, side + "_pressure_drop").fix(dp)
    for uid, name in VALVE_NAMES.items():
        valve = getattr(fs, name)
        ports = {p["key"]: p["stream"] for p in by_unit[uid]}
        inlet = refs[ports["inlet"]]
        outlet = refs[ports["outlet"]]
        rho = value(valve.inlet_state[0].dens_mass)
        dp = inlet["pressure"] - outlet["pressure"]
        opening = 0.033309918350096904 if name == "source_valve" else 0.7
        cv = (
            1 / 3600
            if name == "source_valve"
            else inlet["flow_mass"] / (rho * 999 * dp) ** 0.5
        )
        valve.nominal_density.set_value(rho)
        valve.nominal_pressure_drop.set_value(dp)
        valve.nominal_opening.set_value(opening)
        valve.nominal_Cv.set_value(cv)
        valve.Cv.fix(cv)
        valve.opening[0].set_value(opening)
        if name != "source_valve":
            valve.alpha.set_value(1)
            valve.Cv.fix(cv / opening)
            valve.nominal_Cv.set_value(cv / opening)
        if cal:
            vcal = cal["valves"][name]
            valve.Cv.fix(vcal["Cv"])
            valve.nominal_Cv.set_value(vcal["nominal_Cv"])
            valve.nominal_pressure_drop.set_value(vcal["pressure_drop_Pa"])
            valve.nominal_density.set_value(vcal["density_kg_m3"])
            valve.nominal_opening.set_value(vcal["opening"])
    # Preserve the same public specifications under every fidelity combination.
    fs.compressor.efficiency.fix(properties(objects[1718031])["efficiency_isentropic"])
    for uid, name in (
        (1718048, "hot_water_pump"),
        (1718056, "warm_water_pump"),
        (1718068, "source_pump"),
    ):
        getattr(fs, name).efficiency.fix(properties(objects[uid])["efficiency_pump"])
    fs.warm_water_pump.work.fix(0)
    fs.source_pump.work.fix(
        properties(objects[1718068])["work_mechanical"] * 1000 * load
    )
    fs.source_tank.heat_duty.fix(0)

    def state(sid):
        return fs.stream_states[sid][0]

    for sid in (1718032, 1718049, 1718057):
        state(sid).flow_mass.fix(refs[sid]["flow_mass"] * load)
    source_factor = load if source_flow_factor is None else source_flow_factor
    state(1718073).flow_mass.fix(refs[1718073]["flow_mass"] * source_factor)
    for s in fs.stream_states[1718073]:
        s.flow_mass.set_value(refs[1718073]["flow_mass"] * source_factor)
    for sid in (1718032, 1718044, 1718049, 1718053, 1718055, 1718067, 1718073):
        state(sid).pressure.fix(refs[sid]["pressure"])
    fs.source_temperature = Constraint(
        expr=state(1718073).temperature == refs[1718073]["temperature"] * u.K
    )
    for sid in (1718059, 1718066):
        s = state(sid)
        s.pressure.fix(refs[sid]["pressure"])
        s.enth_mass.fix(value(s.enth_mass))
    state(1718059).flow_mass.fix(refs[1718059]["flow_mass"] * load)
    # Remove only the exact continuity/pressure redundancies of closed circuits.
    fs.expansion_valve.balances[0].material.deactivate()
    fs.source_tank.balances[0].material.deactivate()
    fs.cooling_exchanger.fidelities["low"].hot[0].pressure.deactivate()
    # The high exchanger has multiple cell pressure equations; omit the last one.
    fs.cooling_exchanger.fidelities["high"].hot[0, cells - 1].pressure.deactivate()
    seed_exchangers(m)
    scale_model(m)
    return m


def selectable_units(model):
    return {
        name: getattr(model.fs, name)
        for name in (*HX_NAMES.values(), *VALVE_NAMES.values())
    }


def select_all(model, fidelity):
    for unit in selectable_units(model).values():
        unit.select_fidelity(fidelity)


def calibrate(path=CALIBRATION, cells=4):
    """Fit each exchanger UA to its captured hot outlet; no full-loop fitting."""
    data = snapshot()
    refs = stream_references(data)
    solver = get_solver(
        "ipopt",
        options={"tol": 1e-8, "max_iter": 300, "nlp_scaling_method": "user-scaling"},
    )
    result = {
        "provenance": {
            "flowsheet": data["flowsheet"],
            "cells": cells,
            "method": "Independent high-fidelity exchanger fits to captured inlet states and hot outlet temperature; cold outlet follows conservation.",
        },
        "exchangers": {},
        "valves": {},
    }
    # Explicit standalone fits avoid fixing incompatible measured energy budgets.
    for uid, name in HX_NAMES.items():
        m = ConcreteModel()
        m.fs = FlowsheetBlock(dynamic=False)
        m.fs.water = phase_parameters("h2o")
        m.fs.refrigerant = phase_parameters("n-butane")
        pkgs = {"water": m.fs.water, "n-butane": m.fs.refrigerant}
        ports = {p["key"]: p["stream"] for p in data["ports"] if p["unitOp"] == uid}
        m.fs.hx = HeatExchanger(
            hot_side_property_package=pkgs[refs[ports["hotInlet"]]["component"]],
            cold_side_property_package=pkgs[refs[ports["coldInlet"]]["component"]],
            fidelities={"low": ChenHX(), "high": SegmentedHX(cells)},
        )
        hx = m.fs.hx
        for key, name2 in PORT_NAMES.items():
            seed_state(getattr(hx, name2 + "_state")[0], refs[ports[key]])
        for inlet in (hx.hot_inlet_state[0], hx.cold_inlet_state[0]):
            for v in inlet.define_state_vars().values():
                v.fix()
        hx.hot_outlet_state[0].enth_mass.fix(value(hx.hot_outlet_state[0].enth_mass))
        hx.area.fix(1)
        hx.length.fix(5)
        hx.U.unfix()
        hx.hot_pressure_drop.fix(
            refs[ports["hotInlet"]]["pressure"] - refs[ports["hotOutlet"]]["pressure"]
        )
        hx.cold_pressure_drop.fix(
            refs[ports["coldInlet"]]["pressure"] - refs[ports["coldOutlet"]]["pressure"]
        )
        hx.select_fidelity("high")
        b = hx.fidelities["high"]
        for x in b.interior:
            interpolate(
                b.hot_states[0, x],
                hx.hot_inlet_state[0],
                hx.hot_outlet_state[0],
                x / cells,
            )
            interpolate(
                b.cold_states[0, x],
                hx.cold_outlet_state[0],
                hx.cold_inlet_state[0],
                x / cells,
            )
        for x in b.cells:
            b.cell_duty[0, x].set_value(value(hx.heat_duty[0]) / cells)
        scale_model(m)
        solved = solver.solve(m)
        if not check_optimal_termination(solved):
            raise RuntimeError(f"Calibration failed: {name}")
        result["exchangers"][name] = {
            "UA_W_K": value(hx.U[0]),
            "heat_duty_W": value(hx.heat_duty[0]),
            "cold_outlet_temperature_K": value(hx.cold_outlet_state[0].temperature),
            "captured_cold_outlet_temperature_K": refs[ports["coldOutlet"]][
                "temperature"
            ],
        }
    # Use a full model solely to access reference inlet property expressions.
    m = build_full_flowsheet(calibration_path=None, cells=cells)
    for uid, name in VALVE_NAMES.items():
        v = getattr(m.fs, name)
        ports = {p["key"]: p["stream"] for p in data["ports"] if p["unitOp"] == uid}
        pin = refs[ports["inlet"]]
        pout = refs[ports["outlet"]]
        rho = value(v.inlet_state[0].dens_mass)
        dp = pin["pressure"] - pout["pressure"]
        opening = 0.033309918350096904 if name == "source_valve" else 0.7
        factor = 100 ** (opening - 1) if name == "source_valve" else opening
        cv = pin["flow_mass"] / (rho * 999 * dp) ** 0.5 / factor
        result["valves"][name] = {
            "Cv": cv,
            "nominal_Cv": cv,
            "opening": opening,
            "density_kg_m3": rho,
            "pressure_drop_Pa": dp,
        }
    Path(path).write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--calibrate", action="store_true")
    args = parser.parse_args()
    if args.calibrate:
        calibrate()
    m = build_full_flowsheet()
    select_all(m, "high")
    print("DOF", degrees_of_freedom(m))
    r = get_solver(
        "ipopt",
        options={"tol": 1e-8, "max_iter": 300, "nlp_scaling_method": "user-scaling"},
    ).solve(m, tee=True)
    print(r.solver.termination_condition)
