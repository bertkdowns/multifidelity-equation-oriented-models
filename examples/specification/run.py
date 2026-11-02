"""Build, specify and solve a valve from three separate documents."""

import json
from pathlib import Path

from idaes.core.solvers import get_solver
from idaes.core.util.model_statistics import degrees_of_freedom
from pyomo.environ import assert_optimal_termination, value

from multifidelity.model_language import (
    ImplementationDocument, InformationDocument, SpecificationDocument,
    apply_specification, build_model,
)

HERE = Path(__file__).parent


def run(solver=None):
    implementation = ImplementationDocument.model_validate_json(
        (HERE / "implementation.json").read_text()
    )
    information = InformationDocument.load_json(HERE / "information.json")
    specification = SpecificationDocument.load_json(HERE / "specification.json")
    model = build_model(implementation.model, implementation)
    apply_specification(model, specification, information)
    dof = degrees_of_freedom(model)
    if dof != 0:
        raise RuntimeError(f"Expected a fully specified valve, got {dof} degrees of freedom")
    solver = solver if solver is not None else get_solver("ipopt")
    if not solver.available(False):
        raise RuntimeError("IPOPT is required; install/configure the IDAES solver extensions")
    result = solver.solve(model)
    assert_optimal_termination(result)
    outlet = model.fs.root.structs.outlet
    t = model.fs.time.first()
    outputs = {
        "flow_kg_per_s": value(outlet.flow[t]),
        "pressure_Pa": value(outlet.pressure[t]),
        "enthalpy_J_per_kg": value(outlet.enthalpy[t]),
    }
    print(json.dumps({
        "degrees_of_freedom": dof,
        "termination_condition": str(result.solver.termination_condition),
        "outlet": outputs,
    }, indent=2))
    return model, result, outputs


if __name__ == "__main__":
    run()
