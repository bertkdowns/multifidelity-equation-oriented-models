"""Public PH specifications, physical balances, and two-fidelity operation."""

import pytest

from idaes.core.util.exceptions import InitializationError
from idaes.core.util.model_statistics import degrees_of_freedom
from idaes.models.properties.general_helmholtz import helmholtz_available
from idaes.models.unit_models import Feed
from pyomo.environ import TransformationFactory, Var, check_optimal_termination, value
from pyomo.network import Arc
from pyomo.util.check_units import assert_units_consistent

from case_studies.milk_evaporator.example import build_model, scale_model

pytestmark = pytest.mark.skipif(
    not helmholtz_available(),
    reason="IDAES Helmholtz extensions are required",
)


def solve(model, solver):
    scale_model(model)
    solver.options["nlp_scaling_method"] = "user-scaling"
    model.fs.effect.initialize(solver=solver)
    assert check_optimal_termination(solver.solve(model))


@pytest.mark.parametrize("connected", [False, True])
def test_common_ph_specifications_and_round_trip(connected, solver):
    model = build_model()
    effect = model.fs.effect
    if connected:
        model.fs.feed = Feed(property_package=model.fs.milk)
        for name, variable in effect.milk_inlet.vars.items():
            for key, item in variable.items():
                model.fs.feed.outlet.vars[name][key].fix(value(item))
                item.unfix()
        model.fs.connection = Arc(
            source=model.fs.feed.outlet, destination=effect.milk_inlet
        )
        TransformationFactory("network.expand_arcs").apply_to(model)
    for port in (effect.milk_inlet, effect.milk_outlet):
        assert set(port.vars) == {"flow_mol", "mole_frac_comp", "enth_mol", "pressure"}
    assert set(effect.water_outlet.vars) == {"flow_mol", "enth_mol", "pressure"}
    variables = list(effect.component_data_objects(Var, active=None))
    flags = [(v, v.fixed) for v in variables]
    detailed_outputs = []
    for fidelity in ("high", "low", "high"):
        before = [(v.value, v.fixed) for v in variables]
        effect.select_fidelity(fidelity)
        assert [(v.value, v.fixed) for v in variables] == before
        assert degrees_of_freedom(model) == 0
        assert effect.heat_recovery_effectiveness[0].fixed
        assert not effect.fidelities["high"].heat_exchanger.area.fixed
        effect.heat_recovery_effectiveness.unfix()
        assert degrees_of_freedom(model) == 1
        effect.heat_recovery_effectiveness.fix(0.75)
        assert_units_consistent(model)
        solve(model, solver)
        assert all(v.fixed == fixed for v, fixed in flags)
        assert value(effect.mvr_power[0]) == pytest.approx(4300)
        assert value(effect.heat_recovery_effectiveness[0]) == pytest.approx(0.75)
        assert value(effect.heat_duty[0]) == pytest.approx(
            0.75
            * value(effect.water_outlet_state[0].flow_mol)
            * value(
                effect.recompressed_enthalpy[0]
                - effect.water_outlet_state[0].enth_mol_sat_phase["Liq"]
            ),
            rel=1e-7,
        )
        assert value(effect.milk_outlet_state[0].pressure) == pytest.approx(60000)
        assert value(effect.heat_duty[0]) > value(effect.mvr_power[0])
        assert 0 < value(effect.product_solids_mass_fraction[0]) < 1
        assert value(effect.water_outlet_state[0].flow_mass) > 0
        assert abs(value(effect.component_residual[0, "water"])) < 1e-7
        if fidelity == "low":
            assert abs(value(effect.component_residual[0, "milk_solid"])) < 1e-7
            assert abs(value(effect.energy_residual[0])) < 1e-3
            assert value(effect.heat_recovery_effectiveness[0]) == pytest.approx(0.75)
        else:
            high = effect.fidelities["high"]
            assert value(effect.component_residual[0, "milk_solid"]) == pytest.approx(
                value(high.ignored_solids_flow[0]),
                abs=1e-7,
            )
            assert value(effect.energy_residual[0]) == pytest.approx(
                value(
                    high.translator_energy_loss[0] + high.separator_energy_residual[0]
                ),
                abs=1e-3,
            )
            assert (
                abs(value(effect.energy_residual[0])) / value(effect.heat_duty[0])
                < 1e-4
            )
            detailed_outputs.append(value(effect.milk_outlet_state[0].flow_mass))
    assert detailed_outputs[0] > 0
    assert detailed_outputs[1] == pytest.approx(detailed_outputs[0], rel=1e-6)


def test_detailed_area_is_calculated_for_the_shared_effectiveness(solver):
    model = build_model("high")
    effect = model.fs.effect
    hx = effect.fidelities["high"].heat_exchanger
    solve(model, solver)
    area = value(hx.area)
    assert area == pytest.approx(9.6847, rel=1e-3)
    assert not hx.area.fixed
    effect.heat_recovery_effectiveness.fix(0.74)
    assert degrees_of_freedom(model) == 0
    solve(model, solver)
    assert value(hx.area) > 0
    assert value(hx.area) != pytest.approx(area, rel=1e-3)
    assert value(effect.heat_duty[0]) == pytest.approx(
        0.74
        * value(effect.water_outlet_state[0].flow_mol)
        * value(
            effect.recompressed_enthalpy[0]
            - effect.water_outlet_state[0].enth_mol_sat_phase["Liq"]
        ),
        rel=1e-7,
    )
    assert not hx.area.fixed
    assert effect.heat_recovery_effectiveness[0].fixed


def test_aggregate_responds_to_feed_power_pressure_and_effectiveness(solver):
    model = build_model("low")
    effect = model.fs.effect
    solve(model, solver)
    baseline_water = value(effect.water_outlet_state[0].flow_mol)
    baseline_enthalpy = value(effect.milk_outlet_state[0].enth_mol)
    effect.mvr_power.fix(4500)
    effect.operating_pressure.fix(61000)
    effect.milk_inlet_state[0].enth_mol.fix(
        value(effect.milk_inlet_state[0].enth_mol) + 50
    )
    effect.heat_recovery_effectiveness.fix(0.76)
    solve(model, solver)
    assert value(effect.water_outlet_state[0].flow_mol) != pytest.approx(baseline_water)
    assert value(effect.milk_outlet_state[0].enth_mol) == pytest.approx(
        baseline_enthalpy + 5
    )
    assert value(effect.water_outlet_state[0].pressure) == pytest.approx(
        80322.58595343945 + 1000 + 5
    )
    assert value(effect.heat_recovery_effectiveness[0]) == pytest.approx(0.76)
    assert abs(value(effect.energy_residual[0])) < 1e-3


def test_failed_initialization_restores_specifications(solver):
    model = build_model("low")
    effect = model.fs.effect
    flags = [(v, v.fixed) for v in effect.component_data_objects(Var, active=None)]
    with pytest.raises(InitializationError):
        effect.initialize(solver="ipopt", optarg={"max_iter": 0})
    assert all(v.fixed == fixed for v, fixed in flags)
    assert degrees_of_freedom(model) == 0
    solve(model, solver)
    assert abs(value(effect.energy_residual[0])) < 1e-3
