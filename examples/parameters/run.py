"""Build, specify and solve a valve from three separate catalogs."""

import json
from pathlib import Path

from idaes.core.solvers import get_solver
from idaes.core.util.model_statistics import degrees_of_freedom
from pyomo.environ import assert_optimal_termination, value

from multifidelity.model_language import (
    ModelCatalog, ResourceCatalog, select_parameters,
    apply_parameters, build_model, get_variable, export_workspace,
)

HERE = Path(__file__).parent


def run(solver=None):
    model_catalog = ModelCatalog.load_json(HERE / "model_selection.json")
    resources = ResourceCatalog.load_json(HERE / "resources.json")
    model = build_model("valve", model_catalog)
    selection = select_parameters(model, resources)
    if not selection.complete:
        raise RuntimeError(f"Incomplete parameters: {selection}")
    apply_parameters(model, selection.parameters, resources)
    dof = degrees_of_freedom(model)
    if dof != 0:
        raise RuntimeError(f"Expected a fully specified valve, got {dof} degrees of freedom")
    solver = solver if solver is not None else get_solver("ipopt")
    if not solver.available(False):
        raise RuntimeError("IPOPT is required; install/configure the IDAES solver extensions")
    result = solver.solve(model)
    assert_optimal_termination(result)
    export_workspace(model, resources, status="optimal", solver="ipopt",
                     termination_condition=str(result.solver.termination_condition),
                     parameters=selection.parameters).write_json(HERE / "workspace.json")
    t = model.fs.time.first()
    outputs = {
        "flow_kg_per_s": value(get_variable(model, "outlet.flow")[t]),
        "pressure_Pa": value(get_variable(model, "outlet.pressure")[t]),
        "enthalpy_J_per_kg": value(get_variable(model, "outlet.enthalpy")[t]),
    }
    print(json.dumps({
        "selected_records": list(selection.parameters.parameters),
        "replacements": selection.parameters.replacements,
        "skipped_records": {d["record_tag"]: d["reason"]
                            for d in selection.decisions if not d["selected"]},
        "degrees_of_freedom": dof,
        "termination_condition": str(result.solver.termination_condition),
        "outlet": outputs,
    }, indent=2))
    return model, result, outputs


if __name__ == "__main__":
    run()
