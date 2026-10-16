"""Controlled direct, staged, and residual-triggered valve refinement experiments.

Run from the repository root: uv run python -m case_studies.sghp.experiments
"""

import argparse
import json
import platform
import re
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from time import perf_counter

import idaes
import pyomo
from idaes.core.solvers import get_solver
from idaes.models.properties.iapws95 import iapws95_available
from pyomo.environ import check_optimal_termination, value
from pyomo.opt import SolverStatus

from .source_loop import (
    build_source_loop,
    loop_states,
    reference_case,
    set_initial_guesses,
)


OPERATING_CASES = {
    "reference": {},
    "higher_flow": {"flow_factor": 1.2},
    "lower_pressure": {"pressure_Pa": 250000},
    "below_control_range": {"flow_factor": 0.85},
}
SOLVER_OPTIONS = {"tol": 1e-8, "max_iter": 200}
REFINEMENT_THRESHOLD = 1e-3


def measurements(model):
    fs = model.fs
    unit_energy_errors = []
    mass_errors = [abs(value(s.flow_mass - fs.flow_target)) for s in loop_states(model)]
    for name in ("valve", "pump", "evaporator", "heater", "tank"):
        unit = getattr(fs, name)
        heat = (
            0
            if name == "valve"
            else unit.work[0]
            if name == "pump"
            else unit.heat_duty[0]
        )
        unit_energy_errors.append(
            abs(
                value(
                    unit.outlet_state[0].get_enthalpy_flow_terms("Liq")
                    - unit.inlet_state[0].get_enthalpy_flow_terms("Liq")
                    - heat
                )
            )
        )
    return {
        "opening": value(fs.valve.opening[0]),
        "valve_pressure_drop_Pa": value(fs.valve.pressure_drop[0]),
        "suction_pressure_Pa": value(fs.valve.outlet.pressure[0]),
        "source_heat_added_W": value(fs.heater.heat_duty[0]),
        "nonlinear_residual": value(fs.valve.nonlinear_residual[0]),
        "max_mass_error_kg_s": max(mass_errors),
        "max_unit_energy_error_W": max(unit_energy_errors),
        "loop_energy_error_W": abs(
            value(fs.heater.heat_duty[0] + fs.pump.work[0] + fs.evaporator.heat_duty[0])
        ),
        "active_fidelity": fs.valve.active_fidelity,
    }


def solve_stage(model, fidelity, logfile):
    """One solve, no hidden unit initialization or modification of specifications."""
    model.fs.valve.select_fidelity(fidelity)
    solver = get_solver("ipopt", options=SOLVER_OPTIONS)
    start = perf_counter()
    result = solver.solve(model, logfile=str(logfile), load_solutions=False)
    elapsed = perf_counter() - start
    if result.solver.status in (SolverStatus.ok, SolverStatus.warning) and len(
        result.solution
    ):
        model.solutions.load_from(result)
    log = logfile.read_text() if logfile.exists() else ""
    match = re.search(r"Number of Iterations\.*\s*:\s*(\d+)", log)
    metrics = measurements(model)
    conserved = (
        metrics["max_mass_error_kg_s"] < 1e-6
        and metrics["max_unit_energy_error_W"] < 1e-3
    )
    detailed_valid = (
        conserved
        and metrics["valve_pressure_drop_Pa"] >= 0
        and abs(metrics["nonlinear_residual"]) < 1e-6
    )
    return {
        "fidelity": fidelity,
        "termination": str(result.solver.termination_condition),
        "solver_success": bool(check_optimal_termination(result)),
        "successful": bool(check_optimal_termination(result) and conserved),
        "nonlinear_residual_passed": bool(
            check_optimal_termination(result) and detailed_valid
        ),
        "detailed_validated": bool(
            check_optimal_termination(result)
            and detailed_valid
            and fidelity == "pressure_flow"
        ),
        "iterations": int(match.group(1)) if match else None,
        "elapsed_seconds": elapsed,
        "metrics": metrics,
    }


def run_strategy(*, case, property_fidelity, start, strategy, output_dir):
    build_start = perf_counter()
    model = build_source_loop(
        property_fidelity=property_fidelity, **OPERATING_CASES[case]
    )
    set_initial_guesses(model, start)
    build_seconds = perf_counter() - build_start
    prefix = f"{property_fidelity}_{case}_{start}_{strategy}"
    initial = measurements(model)
    stages = []
    first = "pressure_flow" if strategy == "direct" else "linear"
    stages.append(solve_stage(model, first, output_dir / f"{prefix}_0.log"))
    refined = False
    if stages[0]["successful"] and strategy != "direct":
        refined = (
            strategy == "staged"
            or abs(stages[0]["metrics"]["nonlinear_residual"]) > REFINEMENT_THRESHOLD
        )
        if refined:
            stages.append(
                solve_stage(model, "pressure_flow", output_dir / f"{prefix}_1.log")
            )
    final = stages[-1]
    accepted = final["successful"] and final["metrics"]["valve_pressure_drop_Pa"] >= 0
    if strategy == "selective" and not refined:
        accepted = (
            accepted
            and abs(final["metrics"]["nonlinear_residual"]) <= REFINEMENT_THRESHOLD
        )
    else:
        accepted = accepted and final["detailed_validated"]
    return {
        "case": case,
        "property_fidelity": property_fidelity,
        "start": start,
        "strategy": strategy,
        "initial": initial,
        "stages": stages,
        "refined": refined,
        "accepted": bool(accepted),
        "detailed_validated": final["detailed_validated"],
        "build_seconds": build_seconds,
        "elapsed_seconds": sum(s["elapsed_seconds"] for s in stages),
        "iterations": sum(s["iterations"] for s in stages)
        if all(s["iterations"] is not None for s in stages)
        else None,
        "final": final["metrics"],
    }


def run_experiments(output_dir=None):
    output_dir = Path(output_dir) if output_dir else Path(__file__).parent / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    if not get_solver("ipopt").available(False):
        raise RuntimeError("IPOPT is required to run the case study")
    properties = ["linear", "helmholtz"] if iapws95_available() else ["linear"]
    results = []
    for prop in properties:
        for case in OPERATING_CASES:
            for start in reference_case()["initial_guesses"]:
                for strategy in ("direct", "staged", "selective"):
                    result = run_strategy(
                        case=case,
                        property_fidelity=prop,
                        start=start,
                        strategy=strategy,
                        output_dir=output_dir,
                    )
                    results.append(result)
                    print(
                        f"{prop:9} {case:20} {start:18} {strategy:9} "
                        f"accepted={result['accepted']} iterations={result['iterations']}",
                        flush=True,
                    )
    # Compare engineering outputs with a separately solved detailed root. These
    # reference solves are already present in the grid; no run inherits its state.
    for run in results:
        reference = next(
            r
            for r in results
            if r["property_fidelity"] == run["property_fidelity"]
            and r["case"] == run["case"]
            and r["start"] == "near_reference"
            and r["strategy"] == "direct"
        )
        run["opening_error_vs_reference"] = (
            abs(run["final"]["opening"] - reference["final"]["opening"])
            if reference["accepted"] and run["accepted"]
            else None
        )
    # A diagnostic relaxation, excluded from strategy statistics: a negative
    # required opening explains why lower fidelity cannot rescue this target.
    probes = []
    for prop in properties:
        model = build_source_loop(
            property_fidelity=prop, **OPERATING_CASES["below_control_range"]
        )
        set_initial_guesses(model)
        model.fs.valve.opening[0].setlb(-0.1)
        probes.append(
            {
                "property_fidelity": prop,
                "opening_lower_bound": -0.1,
                "result": solve_stage(
                    model, "pressure_flow", output_dir / f"{prop}_relaxed_opening.log"
                ),
            }
        )
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "idaes": idaes.__version__,
            "pyomo": pyomo.__version__,
            "ipopt": list(get_solver("ipopt").version()),
        },
        "solver_options": SOLVER_OPTIONS,
        "refinement_threshold": REFINEMENT_THRESHOLD,
        "helmholtz_available": iapws95_available(),
        "operating_cases": OPERATING_CASES,
        "reference_case": reference_case(),
        "runs": results,
        "diagnostic_bound_relaxations": probes,
    }
    (output_dir / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def summary_table(report):
    lines = [
        "| Properties | Strategy | Accepted / attempts | Detailed validated | Median total iterations | Median solve seconds |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for prop in sorted({r["property_fidelity"] for r in report["runs"]}):
        for strategy in ("direct", "staged", "selective"):
            runs = [
                r
                for r in report["runs"]
                if r["property_fidelity"] == prop and r["strategy"] == strategy
            ]
            good = [r for r in runs if r["accepted"]]
            iterations = [r["iterations"] for r in good if r["iterations"] is not None]
            lines.append(
                f"| {prop} | {strategy} | {len(good)} / {len(runs)} | "
                f"{sum(r['detailed_validated'] for r in runs)} | "
                f"{median(iterations) if iterations else '—'} | "
                f"{median([r['elapsed_seconds'] for r in good]):.4f} |"
                if good
                else f"| {prop} | {strategy} | 0 / {len(runs)} | 0 | — | — |"
            )
    return "\n".join(lines)


def save_baseline_summary(report, path):
    """Keep a reviewable numerical snapshot alongside the written conclusions."""
    keys = (
        "case",
        "property_fidelity",
        "start",
        "strategy",
        "accepted",
        "detailed_validated",
        "refined",
        "iterations",
        "elapsed_seconds",
        "opening_error_vs_reference",
        "final",
    )
    summary = {
        key: report[key]
        for key in (
            "created_utc",
            "environment",
            "solver_options",
            "refinement_threshold",
            "operating_cases",
            "reference_case",
            "diagnostic_bound_relaxations",
        )
    }
    summary["runs"] = [{key: run[key] for key in keys} for run in report["runs"]]
    Path(path).write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--baseline-summary", type=Path)
    args = parser.parse_args()
    report = run_experiments(args.output_dir)
    if args.baseline_summary:
        save_baseline_summary(report, args.baseline_summary)
    print(summary_table(report))
