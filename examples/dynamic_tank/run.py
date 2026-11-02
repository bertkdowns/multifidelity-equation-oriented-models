"""The same JSON tank in steady mode, implicit simulation, and PETSc.

Run from the repository root:
    .venv/bin/python examples/dynamic_tank/run.py
    .venv/bin/python examples/dynamic_tank/run.py --backend petsc
Requires IPOPT; the second command also requires the IDAES PETSc executable.
"""

import argparse
import json
from pathlib import Path

import pyomo.environ as pyo
from idaes.core.solvers import get_solver
from pyomo.util.check_units import assert_units_consistent

from multifidelity.model_language import build_model

IMPLEMENTATION = Path(__file__).parents[1] / "model_language/tank_mixed.json"
INITIAL_VALUES = json.loads((Path(__file__).parent / "initial_values.json").read_text())


def make_tank(*, mode="dynamic", horizon=1000, time_unit="s"):
    return build_model(
        "tank", IMPLEMENTATION, mode=mode, time_unit=time_unit,
        domain_values={"time": [0, horizon]} if mode == "dynamic" else None,
        initial_values=INITIAL_VALUES if mode == "dynamic" else None,
    )


def fix_inputs(model, *, steady=False, inflow=1, outflow=1, loss=0):
    b = model.fs.root.structs
    for variable, number in (
        (b.parameters.area, 1),
        (b.parameters.density, 1000),
        (b.parameters.heat_capacity, 4180),
        (b.parameters.reference_temperature, 273.15),
        (b.inlet.flow, inflow),
        (b.inlet.temperature, 333.15),
        (b.loss.heat, loss),
    ):
        variable.fix(number)
    if steady:
        # Steady mass conservation calculates withdrawal from inlet flow.
        # Level is an operating specification; steady balances do not set it.
        b.inventory.level.fix(1)
    else:
        b.withdrawal.flow.fix(outflow)
    # Guesses do not fix any additional states or derivatives.
    for t in model.fs.time:
        for variable, guess in (
            (b.inventory.level[t], 1),
            (b.inventory.energy[t], 125400000),
            (b.inventory.temperature[t], 303.15),
            (b.outlet.temperature[t], 303.15),
            (b.outlet.flow[t], outflow),
            (b.withdrawal.flow[t], outflow),
        ):
            if not variable.fixed:
                variable.set_value(guess)


def simulate(model, *, backend="ipopt", nfe=100):
    pyo.TransformationFactory("dae.finite_difference").apply_to(
        model, wrt=model.fs.time, nfe=nfe, scheme="BACKWARD"
    )
    assert_units_consistent(model)
    fix_inputs(model)
    if backend == "petsc":
        from idaes.core.solvers.petsc import petsc_dae_by_time_element

        results = petsc_dae_by_time_element(
            model, model.fs.time, initial_solver="ipopt", interpolate=False,
            ts_options={"--ts_type": "bdf", "--ts_rtol": 1e-8, "--ts_atol": 1e-8},
        )
        for result in results.results:
            pyo.assert_optimal_termination(result)
    elif backend == "ipopt":
        pyo.assert_optimal_termination(get_solver("ipopt").solve(model))
    else:
        raise ValueError(f"Unknown backend {backend!r}")
    return model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["ipopt", "petsc"], default="ipopt")
    args = parser.parse_args()
    steady = make_tank(mode="steady")
    fix_inputs(steady, steady=True)
    pyo.assert_optimal_termination(get_solver("ipopt").solve(steady))
    dynamic = simulate(make_tank(), backend=args.backend,
                       nfe=1 if args.backend == "petsc" else 100)
    for label, model in (("steady", steady), ("dynamic", dynamic)):
        t = model.fs.time.last()
        b = model.fs.root.structs
        print(f"{label}: level={pyo.value(b.inventory.level[t]):.4f} m, "
              f"temperature={pyo.value(b.inventory.temperature[t]):.4f} K")


if __name__ == "__main__":
    main()
