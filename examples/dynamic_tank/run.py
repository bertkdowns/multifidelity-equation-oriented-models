"""The same JSON tank in steady mode, implicit simulation, and PETSc.

Run from the repository root:
    .venv/bin/python examples/dynamic_tank/run.py
    .venv/bin/python examples/dynamic_tank/run.py --backend petsc
Requires IPOPT; the second command also requires the IDAES PETSc executable.
"""

import argparse
from pathlib import Path

import pyomo.environ as pyo
from idaes.core.solvers import get_solver
from pyomo.util.check_units import assert_units_consistent

from multifidelity.model_language import (
    InformationDocument, SpecificationDocument, apply_specification, build_model,
    get_variable,
)

IMPLEMENTATION = Path(__file__).parents[1] / "model_language/tank_mixed.json"
HERE = Path(__file__).parent


def make_tank(*, mode="dynamic", horizon=1000, time_unit="s", library=None):
    return build_model(
        "tank_flowsheet", IMPLEMENTATION, mode=mode, time_unit=time_unit, library=library,
        domain_values={"time": [0, horizon]} if mode == "dynamic" else None,
    )


def specify_tank(model, *, inflow=1, outflow=1, loss=0,
                 initial_values=None):
    """Apply operating and initial specifications together, after construction.

    Experiments may override three operating assumptions or supply alternative
    initial-record IDs. Passing [] omits the default initial conditions.
    """
    information = InformationDocument.load_json(HERE / "information.json")
    overrides = {"inlet_flow": inflow, "withdrawal_flow": outflow, "heat_loss": loss}
    information = InformationDocument([
        {**record.model_dump(), "value": overrides.get(record.id, record.value)}
        for record in information.records
    ])
    name = "specification.json" if model.fs.config.dynamic else "steady_specification.json"
    specification = SpecificationDocument.load_json(HERE / name)
    if initial_values is not None:
        specification = SpecificationDocument.model_validate({
            **specification.model_dump(), "initial_values": initial_values,
        })
    apply_specification(model, specification, information)


def set_initial_guesses(model, *, outflow=1):
    b = model.fs.root.relationship.models.tank.structs
    # Guesses do not fix any additional states or derivatives.
    for variable in model.component_data_objects(pyo.Var):
        if variable.value is None:
            variable.set_value(max(variable.lb or 1, 1))
    for path, family in model._model_language_variables.items():
        if path.endswith("state.pressure"):
            for v in family.values():
                if not v.fixed: v.set_value(101325)
        if path.endswith("state.enthalpy"):
            for v in family.values():
                if not v.fixed: v.set_value(125820.1198085)
    from multifidelity.model_language.standard.initialization import seed_affine_state
    tank = model.fs.root.relationship.models.tank
    pressure = 101325
    inlet_h = 104920.1198085 + 4180 * 35
    contents_h = 104920.1198085 + 4180 * 5
    seed_affine_state(tank.relationship.models.inlet_state, pressure, inlet_h)
    seed_affine_state(tank.relationship.models.contents_state, pressure, contents_h)
    for t in model.fs.time:
        for variable, guess in (
            (b.inventory.level[t], 1),
            (b.inventory.mass[t], 997),
            (b.inventory.energy[t], 997*contents_h-pressure),
            (b.inventory.temperature[t], 303.15),
            (b.inventory.enthalpy[t], contents_h),
            (b.inlet.enthalpy[t], inlet_h),
            (b.outlet.enthalpy[t], contents_h),
            (b.outlet.pressure[t], pressure),
            (b.outlet.flow[t], outflow),
            (b.withdrawal.flow[t], outflow),
        ):
            if not variable.fixed:
                variable.set_value(guess)


def simulate(model, *, backend="ipopt", nfe=100, initial_values=None):
    pyo.TransformationFactory("dae.finite_difference").apply_to(
        model, wrt=model.fs.time, nfe=nfe, scheme="BACKWARD"
    )
    assert_units_consistent(model)
    specify_tank(model, initial_values=initial_values)
    set_initial_guesses(model)
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
    specify_tank(steady)
    set_initial_guesses(steady)
    pyo.assert_optimal_termination(get_solver("ipopt").solve(steady))
    dynamic = simulate(make_tank(), backend=args.backend,
                       nfe=1 if args.backend == "petsc" else 100)
    for label, model in (("steady", steady), ("dynamic", dynamic)):
        t = model.fs.time.last()
        level = get_variable(model, "tank.inventory.level")[t]
        temperature = get_variable(model, "tank.inventory.temperature")[t]
        print(f"{label}: level={pyo.value(level):.4f} m, "
              f"temperature={pyo.value(temperature):.4f} K")


if __name__ == "__main__":
    main()
