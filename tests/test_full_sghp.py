"""Contracts of the coupled case study and flowsheet-level fidelity search."""

import pytest
from idaes.core.util.model_statistics import degrees_of_freedom
from idaes.models.properties.general_helmholtz import helmholtz_available
from pyomo.environ import Var, check_optimal_termination, value
from pyomo.util.check_units import assert_units_consistent

from case_studies.sghp.full_flowsheet import (
    build_full_flowsheet,
    select_all,
    selectable_units,
    scale_model,
)
from case_studies.sghp.full_experiments import diagnostics, run_trial
from case_studies.sghp.structure import structural_report
from case_studies.sghp.source_loop import build_source_loop, set_initial_guesses
from multifidelity.workflow import FidelityChoice, SolveOutcome, run_selection

pytestmark = pytest.mark.skipif(
    not helmholtz_available(), reason="IDAES Helmholtz extensions are required"
)


def test_complete_sghp_conserves_balances_and_preserves_specifications(solver):
    model = build_full_flowsheet()
    select_all(model, "high")
    variables = list(model.component_data_objects(Var, active=None))
    before = [(v.value, v.fixed) for v in variables]
    units = selectable_units(model)
    assert len(units) == 9
    assert degrees_of_freedom(model) == 0
    for unit in units.values():
        unit.select_fidelity("low")
        assert degrees_of_freedom(model) == 0
        unit.select_fidelity("high")
    assert [(v.value, v.fixed) for v in variables] == before
    assert_units_consistent(model)
    structure = structural_report(model)
    assert structure["variables"]["unmatched"] == 0
    assert structure["constraints"]["unmatched"] == 0
    scale_model(model)
    solver.options["nlp_scaling_method"] = "user-scaling"
    assert check_optimal_termination(solver.solve(model))
    metrics, _, accepted = diagnostics(model)
    assert accepted
    assert metrics["global_energy_error_W"] < 1e-3
    assert metrics["external_mass_error_kg_s"] < 1e-7
    assert metrics["steam_outlet_kg_s"] == pytest.approx(0.0209915, rel=0.01)
    assert metrics["compressor_work_W"] == pytest.approx(12916.48, rel=0.01)


@pytest.mark.parametrize("case", ["below_control_range", "low_demand"])
def test_selective_fallback_preserves_full_flowsheet_analysis(case, tmp_path, solver):
    result = run_trial(
        case=case, start="reference", strategy="context", output_dir=tmp_path
    )
    assert result["accepted"]
    assert result["outcome"] == "accepted_approximation"
    assert result["high_count"] == 8
    assert result["assignment"]["source_valve"] == "low"
    assert result["metrics"]["steam_outlet_kg_s"] > 0
    assert result["metrics"]["global_energy_error_W"] < 1e-3
    if case == "low_demand":
        # Consistent signed duties permit the IHX to reverse at low demand.
        assert result["metrics"]["ihx_duty_W"] < 0
        assert result["assignment"]["ihx"] == "high"


def test_failed_refinement_restores_the_last_accepted_process_state(solver):
    model = build_source_loop(flow_factor=0.85)
    set_initial_guesses(model)
    choice = FidelityChoice("valve", model.fs.valve, low="basic", high="pressure_flow")
    saved = {}

    def solve(m):
        result = solver.solve(m)
        accepted = bool(check_optimal_termination(result))
        if accepted:
            saved.update(
                {id(v): v.value for v in m.component_data_objects(Var, active=None)}
            )
        return SolveOutcome(
            accepted,
            str(result.solver.termination_condition),
            0,
            None,
            {"source_heat_W": value(m.fs.heater.heat_duty[0])},
        )

    result = run_selection(model, [choice], solve, strategy="progressive")
    assert result.accepted
    assert len(result.attempts) == 2
    assert not result.attempts[-1]["accepted"]
    assert result.assignment == {"valve": "basic"}
    assert result.metrics["source_heat_W"] == value(model.fs.heater.heat_duty[0])
    assert all(
        v.value == saved[id(v)] for v in model.component_data_objects(Var, active=None)
    )
    assert degrees_of_freedom(model) == 0
