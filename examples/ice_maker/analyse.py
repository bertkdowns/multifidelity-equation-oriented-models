"""Fit a suction probe model and screen conditional R600a cycle states."""

import argparse
import csv
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pyomo.environ as pyo
from idaes.core.solvers import get_solver
from idaes.models.properties.general_helmholtz import (
    AmountBasis,
    HelmholtzParameterBlock,
    HelmholtzThermoExpressions,
)

from multifidelity.model_language import (
    InformationDocument,
    Library,
    SpecificationDocument,
    apply_specification,
    build_model,
    get_variable,
)
from multifidelity.model_language.standard.thermo import _fluid_data

HERE = Path(__file__).resolve().parent
CHANNELS = ("Suction", "Discharge", "Pre-capillary", "Post-capillary", "Ambient", "Water")
KELVIN = 273.15
GRID_SECONDS = 5
# Elapsed seconds from each file's first timestamp. Separate, contiguous episodes.
EXPORT_FIT, EXPORT_CHECK = (1000, 1420), (1510, 1940)
HOT_FIT, HOT_CHECK = (2105, 2635), (2940, 3185)


def load_log(path):
    frames = {}
    devices = set()
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            channel = int(row["channel"])
            if not 1 <= channel <= 6:
                continue
            devices.add(row["device"])
            frame = frames.setdefault(int(row["time"]), {})
            if channel in frame:
                raise ValueError(f"{path}: duplicate channel {channel} at {row['time']}")
            frame[channel] = float(row["temperature_c"])
    if len(devices) != 1 or not frames or any(len(frame) != 6 for frame in frames.values()):
        raise ValueError(f"{path}: expected one device and complete six-channel frames")
    timestamps = sorted(frames)
    time = (np.array(timestamps) - timestamps[0]) / 1000
    data = np.array([[frames[t][c] for c in range(1, 7)] for t in timestamps])
    # Recorder sentinel. Other suspect early readings are kept out of the fit by window.
    data[data == -270] = np.nan
    start = datetime.fromtimestamp(timestamps[0] / 1000, ZoneInfo("Pacific/Auckland"))
    print(f"{path.name}: {next(iter(devices))}, {len(time)} frames, {start.isoformat()}, "
          f"{time[-1]:.1f} s")
    return time, data


def window(log, limits):
    time, data = log
    grid = np.arange(limits[0], limits[1] + 1, GRID_SECONDS)
    if grid[0] < time[0] or grid[-1] > time[-1]:
        raise ValueError(f"Window {limits} extends outside the supplied log")
    values = np.column_stack([np.interp(grid, time, column) for column in data.T])
    if not np.isfinite(values[:, [0, 4, 5]]).all():
        raise ValueError(f"Missing suction, ambient or water data in window {limits}")
    return grid, values


def fit_response(grid, data, *, water_only):
    model = build_model(
        "suction_response", {"relationship": "lumped"}, library=Library(HERE),
        mode="dynamic", domain_values={"time": grid.tolist()},
    )
    pyo.TransformationFactory("dae.finite_difference").apply_to(
        model, wrt=model.fs.time, nfe=len(grid) - 1, scheme="BACKWARD",
    )
    paths = {"water": "boundary.water", "ambient": "boundary.ambient", "suction": "state.suction"}
    information = InformationDocument([
        dict(id=name, tag=f"channel {channel}", information_type="sensor_reading",
             variable_path=paths[name], type="series", value=data[:, channel - 1] + KELVIN,
             unit="K", trust_rank=5)
        for name, channel in (("water", 6), ("ambient", 5), ("suction", 1))
    ])
    information.add(dict(id="initial", tag="channel 1", information_type="sensor_reading",
                         variable_path=paths["suction"], value=data[0, 0] + KELVIN,
                         unit="K", trust_rank=5))
    apply_specification(
        model, SpecificationDocument(specifications=("water", "ambient"), initial_values=("initial",)),
        information,
    )
    suction = get_variable(model, paths["suction"])
    target = information.get("suction").values_for(suction)
    for time, measurement in target.items():
        suction[time].set_value(measurement)
    parameters = [get_variable(model, f"parameters.{name}") for name in ("tau", "water_weight", "offset")]
    if water_only:
        parameters[1].fix(1)
    model.fit = pyo.Objective(expr=sum(((suction[t] / pyo.units.K) - target[t])**2 for t in target))
    pyo.assert_optimal_termination(get_solver("ipopt").solve(model))
    return tuple(pyo.value(p) for p in parameters), np.array([pyo.value(suction[t]) - KELVIN for t in grid])


def replay(grid, data, parameters):
    tau, weight, offset = parameters
    equilibrium = data[:, 4] + weight * (data[:, 5] - data[:, 4]) + offset
    result = np.empty(len(data))
    result[0] = data[0, 0]
    for i, dt in enumerate(np.diff(grid), start=1):
        result[i] = (tau * result[i - 1] + dt * equilibrium[i]) / (tau + dt)
    return result


def rmse(prediction, observation):
    return np.sqrt(np.mean((prediction - observation)**2))


def screen_cycle(thermo, values, superheat, subcooling):
    """Four states at assumed pressures with an isenthalpic capillary."""
    suction, discharge, pre_cap, post_cap, ambient, water = values
    evap, cond = suction - superheat, pre_cap + subcooling
    p_low = thermo.p_sat(T=(evap + KELVIN) * pyo.units.K)
    p_high = thermo.p_sat(T=(cond + KELVIN) * pyo.units.K)
    if not evap < cond < discharge:
        raise ValueError("Assumed states require evaporation < condensation < discharge")
    temperature = pyo.units.K
    h1 = thermo.h_vap(T=(suction + KELVIN) * temperature, p=p_low)
    h2 = thermo.h_vap(T=(discharge + KELVIN) * temperature, p=p_high)
    h3 = thermo.h_liq(T=(pre_cap + KELVIN) * temperature, p=p_high)
    h4 = h3
    s1 = thermo.s_vap(T=(suction + KELVIN) * temperature, p=p_low)
    h2s = thermo.h(s=s1, p=p_high)
    work, q_evap, q_cond = map(pyo.value, (h2 - h1, h1 - h4, h2 - h3))
    flash_quality = pyo.value(thermo.x(h=h4, p=p_low))
    flash_c = pyo.value(thermo.T(h=h4, p=p_low)) - KELVIN
    return dict(
        p_low_bar=pyo.value(p_low) / 1e5, p_high_bar=pyo.value(p_high) / 1e5,
        flash_quality=flash_quality, flash_c=flash_c, flash_minus_probe=flash_c - post_cap,
        water_minus_evap=water - evap, ambient_minus_suction=ambient - suction,
        evap_kJ_kg=q_evap / 1e3, cond_kJ_kg=q_cond / 1e3, work_kJ_kg=work / 1e3,
        eta_isentropic=pyo.value(h2s - h1) / work,
    )


def saturation(thermo, celsius):
    t = (celsius + KELVIN) * pyo.units.K
    return (
        pyo.value(thermo.p_sat(T=t)) / 1e5,
        pyo.value(1 / thermo.v_liq_sat(T=t)),
        pyo.value(1 / thermo.v_vap_sat(T=t)),
    )


def report_charge_balance(thermo, values):
    """Close the hot-peak inventory with the known charge and assumed volumes."""
    charge_g = 24
    high_bar = 15.6
    suction, _, pre_cap, *_ = values
    cond = pyo.value(thermo.T_sat(p=high_bar * 1e5 * pyo.units.Pa)) - KELVIN
    low_bar, low_liquid, low_vapour = saturation(thermo, suction)
    _, high_liquid, high_vapour = saturation(thermo, cond)
    cycle = screen_cycle(thermo, values, superheat=0, subcooling=cond - pre_cap)
    print(f"24 g hot-peak case: {low_bar:.2f}/{high_bar:.2f} bar abs, "
          f"{cond:.2f} °C condensing, {cycle['eta_isentropic']:.1%} isentropic efficiency")
    print(f"  Flash: {cycle['flash_c']:.2f} °C, {cycle['flash_quality']:.1%} vapour by mass, "
          f"{abs(cycle['flash_minus_probe']):.2f} K from the post-capillary probe")
    print(f"  Water to evaporation approach: {cycle['water_minus_evap']:.2f} K; "
          f"evaporator/condenser specific duties: {cycle['evap_kJ_kg']:.1f}/"
          f"{cycle['cond_kJ_kg']:.1f} kJ/kg")
    print("  High mL  External low mL  Low liquid vol%  Compressor g  "
          "External low g  High g  High liquid vol%  High liquid mL")
    cases = (
        (50, 30, 0.02, 5), (50, 30, 0.02, 0), (50, 30, 0.02, 2), (50, 30, 0.02, 8),
        (35, 30, 0.02, 5), (100, 30, 0.02, 5), (50, 15, 0.02, 5), (50, 60, 0.02, 5),
        (50, 30, 0.10, 5), (50, 30, 1.00, 5),
    )
    for high_ml, low_ml, low_fraction, compressor_g in cases:
        low_g = low_ml / 1000 * (low_vapour + low_fraction * (low_liquid - low_vapour))
        high_g = charge_g - compressor_g - low_g
        high_fraction = (1000 * high_g / high_ml - high_vapour) / (high_liquid - high_vapour)
        liquid = (f"{high_fraction:16.1%} {high_ml * high_fraction:15.2f}"
                  if 0 <= high_fraction <= 1 else "  infeasible at these assumptions")
        print(f"  {high_ml:7} {low_ml:16} {low_fraction:15.0%} {compressor_g:13.1f} "
              f"{low_g:14.2f} {high_g:7.2f} {liquid}")
    baseline_low_g = 0.030 * (0.98 * low_vapour + 0.02 * low_liquid)
    min_high_ml = 1000 * (charge_g - 5 - baseline_low_g) / high_liquid
    print(f"  With 5 g in the compressor and 2% external low-side liquid, the high side needs "
          f"at least {min_high_ml:.1f} mL even if full of liquid at condensing temperature")


def report_cycle(export, hot):
    time, data = hot
    peak = np.nanargmax(data[:, 1])
    export_time, export_data = export
    cold = np.flatnonzero((export_time >= 1510) & (export_time <= 1954))
    cold_point = cold[np.nanargmin(export_data[cold, 0])]
    # All calculations stay inside the context owning the i-butane EOS data.
    with _fluid_data("i-butane"):
        model = pyo.ConcreteModel()
        model.properties = HelmholtzParameterBlock(pure_component="i-butane", amount_basis=AmountBasis.MASS)
        thermo = HelmholtzThermoExpressions(model, model.properties)
        print(f"Cooler run at {export_time[cold_point]:.2f} s: {export_data[cold_point].round(2)} °C")
        cold_result = screen_cycle(thermo, export_data[cold_point], 5, 5)
        print(f"Cold point, 5 K superheat and subcooling: {cold_result['p_low_bar']:.2f} bar abs "
              f"low side, {cold_result['flash_c']:.2f} °C predicted post-capillary")
        print(f"Hot discharge peak at {time[peak]:.2f} s; temperatures {data[peak].round(2)} °C")
        for superheat, subcooling in ((0, 5), (5, 0), (5, 5), (5, 10), (10, 5)):
            result = screen_cycle(thermo, data[peak], superheat, subcooling)
            print(f"SH {superheat}, SC {subcooling} K: "
                  + str({k: round(float(v), 3) for k, v in result.items()}))
        print("Saturation properties (temperature °C, bar abs, liquid and vapour g/L):")
        for c in (data[peak, 0] - 3, data[peak, 0], data[peak, 0] + 3,
                  data[peak, 2] + 5, data[peak, 3], 100, 105, 110):
            p, liquid, vapour = saturation(thermo, c)
            print(f"{c:7.2f} {p:7.3f} {liquid:8.2f} {vapour:8.2f}")
        report_charge_balance(thermo, data[peak])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path, help="Path to export (2).csv")
    parser.add_argument("hot", type=Path, help="Path to IceMaker Hot until liquid slug.csv")
    parser.add_argument("--plot", type=Path, help="Optional destination for a diagnostic PNG")
    args = parser.parse_args()
    cases = (
        ("6 Nov export", load_log(args.export), EXPORT_FIT, EXPORT_CHECK),
        ("10 Nov hot run", load_log(args.hot), HOT_FIT, HOT_CHECK),
    )
    if args.plot:
        import matplotlib.pyplot as plt

        figure, axes = plt.subplots(2, 2, figsize=(13, 7), layout="constrained")
    for i, (label, log, fit_limits, check_limits) in enumerate(cases):
        train_t, train = window(log, fit_limits)
        check_t, check = window(log, check_limits)
        print(label)
        for water_only in (True, False):
            name = "Water only" if water_only else "Water + ambient"
            parameters, predicted = fit_response(train_t, train, water_only=water_only)
            np.testing.assert_allclose(predicted, replay(train_t, train, parameters), atol=1e-5, rtol=0)
            validation = replay(check_t, check, parameters)
            print(f"{name}: tau={parameters[0]:.2f} s, water weight={parameters[1]:.3f}, "
                  f"offset={parameters[2]:.2f} K; "
                  f"fit/check RMSE={rmse(predicted, train[:, 0]):.2f}/"
                  f"{rmse(validation, check[:, 0]):.2f} °C")
            if args.plot:
                axes[i, 1].plot(check_t / 60, validation, label=name)
        print(f"Hold-last check RMSE={rmse(check[0, 0], check[:, 0]):.2f} °C")
        if args.plot:
            time, data = log
            for name, column in zip(CHANNELS, data.T, strict=True):
                axes[i, 0].plot(time / 60, column, linewidth=0.9, label=name)
            for limits, name, color in ((fit_limits, "Fit window", "tab:blue"),
                                        (check_limits, "Check window", "tab:orange")):
                axes[i, 0].axvspan(*(np.array(limits) / 60), color=color, alpha=0.12, label=name)
            axes[i, 0].set(title=label, ylabel="Measured temperature (°C)", ylim=(-5, 97))
            axes[i, 0].legend(loc="upper left", ncol=2, fontsize=8)
            axes[i, 1].plot(check_t / 60, check[:, 0], color="black", label="Measured suction")
            axes[i, 1].set(title=f"{label} · held-out window", ylabel="Suction temperature (°C)")
            axes[i, 1].legend(fontsize=8)
            for axis in axes[i]:
                axis.set_xlabel("Elapsed time (min)")
                axis.grid(alpha=0.2)
    report_cycle(cases[0][1], cases[1][1])
    if args.plot:
        figure.savefig(args.plot, dpi=150)


if __name__ == "__main__":
    main()
