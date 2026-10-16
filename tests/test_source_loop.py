"""Research contracts of the reduced source-loop integration."""

import pytest

from idaes.core.util.model_statistics import degrees_of_freedom
from idaes.models.properties.iapws95 import iapws95_available
from pyomo.environ import check_optimal_termination, value
from pyomo.util.check_units import assert_units_consistent

from case_studies.sghp.experiments import measurements, run_strategy
from case_studies.sghp.source_loop import (
    build_source_loop,
    public_variables,
    reference_case,
    set_initial_guesses,
)


@pytest.mark.parametrize("properties", ["linear", "helmholtz"])
def test_source_loop_switch_preserves_specifications_and_conserves_energy(
    properties, solver
):
    if properties == "helmholtz" and not iapws95_available():
        pytest.skip("IDAES Helmholtz extensions required")
    m = build_source_loop(property_fidelity=properties)
    set_initial_guesses(m, "reversed_pressure")
    flags = [(v, v.fixed, v.value) for v in public_variables(m) if v.fixed]
    for fidelity in ("linear", "pressure_flow", "linear", "pressure_flow"):
        before = [(v, v.value, v.fixed) for v in public_variables(m)]
        m.fs.valve.select_fidelity(fidelity)
        assert all(v.value == old and v.fixed == fixed for v, old, fixed in before)
        assert degrees_of_freedom(m) == 0
        assert_units_consistent(m)
        assert check_optimal_termination(solver.solve(m))
        assert all(v.fixed == fixed and v.value == old for v, fixed, old in flags)
        metrics = measurements(m)
        assert metrics["valve_pressure_drop_Pa"] > 0
        assert metrics["max_mass_error_kg_s"] < 1e-6
        assert metrics["max_unit_energy_error_W"] < 1e-3
        assert metrics["loop_energy_error_W"] < 1e-3
        if fidelity == "pressure_flow":
            assert abs(metrics["nonlinear_residual"]) < 1e-6
    if properties == "helmholtz":
        ref = reference_case()["reference_solution"]
        assert value(m.fs.valve.opening[0]) == pytest.approx(
            ref["valve_opening"], abs=2e-6
        )
        assert value(m.fs.valve.pressure_drop[0]) == pytest.approx(
            ref["valve_pressure_drop_Pa"], abs=2
        )


def test_initialization_strategies_reach_same_detailed_root_from_same_start(
    solver, tmp_path
):
    direct = run_strategy(
        case="reference",
        property_fidelity="linear",
        start="reversed_pressure",
        strategy="direct",
        output_dir=tmp_path,
    )
    staged = run_strategy(
        case="reference",
        property_fidelity="linear",
        start="reversed_pressure",
        strategy="staged",
        output_dir=tmp_path,
    )
    assert direct["initial"] == staged["initial"]
    assert direct["detailed_validated"]
    assert staged["detailed_validated"]
    assert staged["final"]["opening"] == pytest.approx(
        direct["final"]["opening"], abs=1e-7
    )
    assert staged["iterations"] == sum(s["iterations"] for s in staged["stages"])


@pytest.mark.parametrize("case, refined", [("reference", False), ("higher_flow", True)])
def test_residual_trigger_selects_required_valve_fidelity(
    case, refined, solver, tmp_path
):
    result = run_strategy(
        case=case,
        property_fidelity="linear",
        start="near_reference",
        strategy="selective",
        output_dir=tmp_path,
    )
    assert result["refined"] == refined
    assert result["accepted"]
    assert result["final"]["active_fidelity"] == (
        "pressure_flow" if refined else "linear"
    )
    assert abs(result["final"]["nonlinear_residual"]) < (1e-6 if refined else 1e-3)
