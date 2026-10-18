"""Reproducible multi-unit selection study on the coupled SGHP reconstruction."""

import argparse
from collections import Counter
from dataclasses import asdict
import json
from math import isfinite
from pathlib import Path
import re
from time import perf_counter

from idaes.core.solvers import get_solver
from pyomo.environ import Constraint, Var, check_optimal_termination, value, units as u
from pyomo.opt import SolverStatus

from multifidelity.workflow import FidelityChoice, SolveOutcome, run_selection
from .full_flowsheet import (
    CALIBRATION,
    HERE,
    HX_NAMES,
    VALVE_NAMES,
    build_full_flowsheet,
    scale_model,
    seed_exchangers,
    selectable_units,
    select_all,
)
from .structure import structural_report

CASES = {
    "reference": {},
    "below_control_range": {"source_flow_factor": 0.85},
    "low_demand": {"load": 0.1},
    "reduced_source_flow": {"source_flow_factor": 0.6},
}
STARTS = ("reference", "perturbed")
STRATEGIES = (
    "all_high",
    "all_low",
    "manual",
    "progressive",
    "failure_driven",
    "residual",
    "structure",
    "context",
    "grouped_refinement",
)
SOLVER_OPTIONS = {
    "tol": 1e-8,
    "max_iter": 80,
    "max_cpu_time": 8,
    "nlp_scaling_method": "user-scaling",
}
# Deliberate baseline ordering: known source-loop vulnerability first, followed
# by all other valves and exchangers. Residual/structural searches may differ.
ORDER = (
    "source_valve",
    "expansion_valve",
    "hot_water_valve",
    "steam_valve",
    "ihx",
    "cooling_exchanger",
    "subcooler",
    "evaporator",
    "condenser",
)


def set_start(model, name):
    if name == "reference":
        return
    if name != "perturbed":
        raise ValueError(name)
    for v in model.component_data_objects(Var, active=None):
        if v.fixed:
            continue
        if v.local_name == "flow_mass":
            v.set_value(value(v) * 0.7)
        elif v.local_name == "enth_mass":
            v.set_value(value(v) + 10000)
    model.fs.source_valve.outlet_state[0].pressure.set_value(400000)
    model.fs.source_pump.inlet_state[0].pressure.set_value(400000)
    for name in VALVE_NAMES.values():
        getattr(model.fs, name).opening[0].set_value(0.8)
    model.fs.source_valve.opening[0].set_value(0.1)
    seed_exchangers(model)


def constraint_error(c):
    body = value(c.body)
    lo = value(c.lower) if c.has_lb() else None
    hi = value(c.upper) if c.has_ub() else None
    return max(0, 0 if lo is None else lo - body, 0 if hi is None else body - hi)


def diagnostics(model):
    """Acceptance includes equation residuals, bounds, and exchanger direction."""
    fs = model.fs
    units = selectable_units(model)
    scaled = []
    mass = []
    energy = []
    for c in model.component_data_objects(Constraint, active=True):
        error = constraint_error(c)
        scaled.append(error * model.scaling_factor.get(c, 1))
        unit = str(u.get_units(c.body))
        if unit == "kg/s":
            mass.append(error)
        if unit in {"W", "J/s"}:
            energy.append(error)
    violation = 0
    for v in model.component_data_objects(Var, active=True):
        if v.value is None:
            continue
        x = value(v)
        if v.has_lb():
            violation = max(
                violation, max(0, value(v.lb) - x) * model.scaling_factor.get(v, 1)
            )
        if v.has_ub():
            violation = max(
                violation, max(0, x - value(v.ub)) * model.scaling_factor.get(v, 1)
            )
    approaches = []
    directional_approaches = []
    for name in HX_NAMES.values():
        hx = units[name]
        first_approach = len(approaches)
        if hx.active_fidelity == "high":
            b = hx.fidelities["high"]
            n = len(b.cells)
            for x in range(n + 1):
                hot = (
                    hx.hot_inlet_state[0]
                    if x == 0
                    else hx.hot_outlet_state[0]
                    if x == n
                    else b.hot_states[0, x]
                )
                cold = (
                    hx.cold_outlet_state[0]
                    if x == 0
                    else hx.cold_inlet_state[0]
                    if x == n
                    else b.cold_states[0, x]
                )
                approaches.append(value(hot.temperature - cold.temperature))
        else:
            approaches.extend(
                (
                    value(
                        hx.hot_inlet_state[0].temperature
                        - hx.cold_outlet_state[0].temperature
                    ),
                    value(
                        hx.hot_outlet_state[0].temperature
                        - hx.cold_inlet_state[0].temperature
                    ),
                )
            )
        direction = 1 if value(hx.heat_duty[0]) >= 0 else -1
        directional_approaches.extend(
            direction * x for x in approaches[first_approach:]
        )
    work = value(
        fs.compressor.work[0]
        + fs.hot_water_pump.work[0]
        + fs.warm_water_pump.work[0]
        + fs.source_pump.work[0]
    )
    steam = fs.steam_valve.outlet_state[0]
    fresh = fs.warm_water_mixer.makeup_state[0]
    cooling_in = fs.cooling_exchanger.cold_inlet_state[0]
    cooling_out = fs.cooling_exchanger.cold_outlet_state[0]
    external_energy = (
        value(fs.source_heater.heat_duty[0])
        + work
        + value(
            fresh.flow_mass * fresh.enth_mass
            + cooling_in.flow_mass * cooling_in.enth_mass
            - steam.flow_mass * steam.enth_mass
            - cooling_out.flow_mass * cooling_out.enth_mass
        )
    )
    metrics = {
        "max_scaled_equation_residual": max(scaled, default=0),
        "max_scaled_bound_violation": violation,
        "max_mass_residual_kg_s": max(mass, default=0),
        "max_energy_residual_W": max(energy, default=0),
        "global_energy_error_W": abs(external_energy),
        "external_mass_error_kg_s": abs(value(fresh.flow_mass - steam.flow_mass)),
        "minimum_temperature_approach_K": min(approaches),
        "minimum_directional_approach_K": min(directional_approaches),
        "steam_outlet_kg_s": value(steam.flow_mass),
        "dry_steam_kg_s": value(steam.flow_mass * steam.vapor_frac),
        "steam_vapor_fraction": value(steam.vapor_frac),
        "compressor_work_W": value(fs.compressor.work[0]),
        "total_work_W": work,
        "heating_COP": value(fs.condenser.heat_duty[0] + fs.subcooler.heat_duty[0])
        / work
        if work > 0
        else 0,
        "steam_COP": value(steam.flow_mass * (steam.enth_mass - fresh.enth_mass)) / work
        if work > 0
        else 0,
        "source_heat_W": value(fs.source_heater.heat_duty[0]),
    }
    metrics.update(
        {
            f"{name}_duty_W": value(units[name].heat_duty[0])
            for name in HX_NAMES.values()
        }
    )
    metrics.update(
        {
            f"{name}_opening": value(units[name].opening[0])
            for name in VALVE_NAMES.values()
        }
    )
    residuals = {
        name: max(
            (
                constraint_error(c) * model.scaling_factor.get(c, 1)
                for c in unit.component_data_objects(Constraint, active=True)
            ),
            default=0,
        )
        for name, unit in units.items()
    }
    accepted = (
        all(isfinite(v) for v in metrics.values())
        and metrics["max_scaled_equation_residual"] < 1e-6
        and violation < 1e-6
        and metrics["minimum_directional_approach_K"] >= -1e-4
        and metrics["global_energy_error_W"] < 1e-2
        and metrics["max_mass_residual_kg_s"] < 1e-6
        and metrics["max_energy_residual_W"] < 1e-2
    )
    return metrics, residuals, accepted


def make_solve(output_dir, prefix):
    count = 0

    def solve(model):
        nonlocal count
        scale_model(model)
        log = output_dir / f"{prefix}_{count}.log"
        count += 1
        solver = get_solver("ipopt", options=SOLVER_OPTIONS)
        start = perf_counter()
        result = solver.solve(model, logfile=str(log), load_solutions=False)
        elapsed = perf_counter() - start
        if result.solver.status in (SolverStatus.ok, SolverStatus.warning) and len(
            result.solution
        ):
            model.solutions.load_from(result)
        match = re.search(r"Number of Iterations\.*\s*:\s*(\d+)", log.read_text())
        metrics, residuals, valid = diagnostics(model)
        return SolveOutcome(
            bool(check_optimal_termination(result) and valid),
            str(result.solver.termination_condition),
            elapsed,
            int(match[1]) if match else None,
            metrics,
            residuals,
        )

    return solve


def run_trial(*, case, start, strategy, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    began = perf_counter()
    model = build_full_flowsheet(**CASES[case])
    set_start(model, start)
    select_all(model, "high")
    report = structural_report(model)
    choices = [FidelityChoice(name, selectable_units(model)[name]) for name in ORDER]
    coarse = (
        ("source_valve",)
        if strategy == "manual" or (strategy == "context" and case != "reference")
        else ()
    )
    build_seconds = perf_counter() - began
    selection_start = perf_counter()
    result = run_selection(
        model,
        choices,
        make_solve(output_dir, f"{case}_{start}_{strategy}"),
        strategy=strategy,
        groups=report["equipment_groups"],
        coarse_units=coarse,
    )
    selection_seconds = perf_counter() - selection_start
    record = asdict(result)
    record.update(
        case=case,
        start=start,
        strategy=strategy,
        build_seconds=build_seconds,
        selection_seconds=selection_seconds,
        total_wall_seconds=perf_counter() - began,
        total_solve_seconds=sum(a["elapsed_seconds"] for a in result.attempts),
        total_iterations=sum(a["iterations"] or 0 for a in result.attempts),
        high_count=sum(f == "high" for f in result.assignment.values()),
        outcome="failed"
        if not result.accepted
        else "all_high_solution"
        if all(f == "high" for f in result.assignment.values())
        else "accepted_approximation",
        structural_report=report,
        policy_coarse_units=list(coarse),
    )
    return record


def run_grid(
    output_dir=HERE / "results" / "full",
    cases=tuple(CASES),
    starts=STARTS,
    strategies=STRATEGIES,
):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    outcomes = []
    for case in cases:
        for start in starts:
            for strategy in strategies:
                trial = run_trial(
                    case=case, start=start, strategy=strategy, output_dir=output_dir
                )
                outcomes.append(trial)
                print(
                    case,
                    start,
                    strategy,
                    trial["outcome"],
                    trial["high_count"],
                    trial["total_iterations"],
                    flush=True,
                )
                # Checkpoint long experiments without discarding finished trials.
                (output_dir / "results.json").write_text(
                    json.dumps(outcomes, indent=2) + "\n"
                )
    # Errors are only meaningful against an accepted all-high solution at the same
    # operating condition. A different successful start can supply that reference.
    for trial in outcomes:
        reference = next(
            (
                r
                for r in outcomes
                if r["case"] == trial["case"]
                and r["accepted"]
                and r["high_count"] == len(ORDER)
            ),
            None,
        )
        trial["errors_vs_all_high"] = (
            {
                key: trial["metrics"][key] - reference["metrics"][key]
                for key in (
                    "steam_outlet_kg_s",
                    "dry_steam_kg_s",
                    "heating_COP",
                    "steam_COP",
                    "source_heat_W",
                )
            }
            if reference is not None and trial["accepted"]
            else None
        )
    report = {
        "solver_options": SOLVER_OPTIONS,
        "calibration_file": str(CALIBRATION.relative_to(HERE)),
        "cases": {c: CASES[c] for c in cases},
        "starts": list(starts),
        "selection_order": list(ORDER),
        "outcomes": outcomes,
        "summary": {
            s: dict(Counter(r["outcome"] for r in outcomes if r["strategy"] == s))
            for s in strategies
        },
    }
    (output_dir / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=HERE / "results" / "full")
    parser.add_argument("--case", action="append", choices=CASES)
    parser.add_argument("--start", action="append", choices=STARTS)
    parser.add_argument("--strategy", action="append", choices=STRATEGIES)
    parser.add_argument("--baseline-summary", type=Path)
    args = parser.parse_args()
    report = run_grid(
        args.output_dir,
        args.case or tuple(CASES),
        args.start or STARTS,
        args.strategy or STRATEGIES,
    )
    if args.baseline_summary:
        args.baseline_summary.write_text(json.dumps(report, indent=2) + "\n")
