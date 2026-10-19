"""The isolated SGHP cycle conserves energy across nested representation switches."""

import pytest
from idaes.core.util.model_statistics import degrees_of_freedom
from idaes.models.properties.general_helmholtz import helmholtz_available
from pyomo.environ import Constraint, Var, check_optimal_termination, value, units as u
from pyomo.util.check_units import assert_units_consistent

from case_studies.sghp.heat_pump_cycle import build_model
from case_studies.sghp.full_flowsheet import scale_model
from multifidelity.unit_models.streams import enthalpy_flow

pytestmark = pytest.mark.skipif(
    not helmholtz_available(), reason="IDAES Helmholtz extensions are required"
)


def assert_conservation(hp):
    cycle = hp.fidelities["cycle"]
    source_loss = value(enthalpy_flow(hp.source_inlet_state[0])
                        - enthalpy_flow(hp.source_outlet_state[0]))
    heating = value(hp.heating_duty[0])
    power = value(hp.electrical_power[0])
    assert source_loss > 0
    assert power > 0
    assert heating == pytest.approx(source_loss + power, abs=1e-3)
    assert power == pytest.approx(value(cycle.compressor.work[0]), abs=1e-5)
    assert heating == pytest.approx(
        value(cycle.condenser.heat_duty[0] + cycle.subcooler.heat_duty[0]), abs=1e-3)
    for side in ("source", "sink"):
        inlet = getattr(hp, side + "_inlet_state")[0]
        outlet = getattr(hp, side + "_outlet_state")[0]
        assert value(inlet.flow_mass) == pytest.approx(value(outlet.flow_mass))
    compressor_flow = value(cycle.compressor.inlet_state[0].flow_mass)
    assert value(cycle.expansion_valve.outlet_state[0].flow_mass) == pytest.approx(compressor_flow)
    assert value(cycle.evaporator.cold_outlet_state[0].flow_mass) == pytest.approx(compressor_flow)


def test_cycle_round_trip_and_nested_choices(solver):
    m = build_model()
    hp = m.fs.hp
    cycle = hp.fidelities["cycle"]
    assert degrees_of_freedom(m) == 0
    assert_units_consistent(m)
    solver.options["nlp_scaling_method"] = "user-scaling"
    hp.initialize(solver=solver)
    assert_conservation(hp)
    power = value(hp.electrical_power[0])
    assert power == pytest.approx(12838.10, rel=0.01)
    assert value(cycle.ihx.heat_duty[0]) > 0

    # Specify the aggregate problem explicitly; selection itself changes no flags.
    hp.fidelities["cop"].COP.fix(value(hp.heating_duty[0]) / power)
    # A PH water outlet can be two-phase: temperature alone does not fix duty.
    hp.sink_target = Constraint(expr=hp.heating_duty[0]
                               == value(hp.heating_duty[0]) * u.W)
    variables = list(m.component_data_objects(Var, active=None))
    before = [(v.value, v.fixed) for v in variables]
    hp.select_fidelity("cop")
    assert [(v.value, v.fixed) for v in variables] == before
    assert degrees_of_freedom(m) == 0
    scale_model(m)
    hp.initialize(solver=solver)
    assert value(hp.electrical_power[0]) == pytest.approx(power, rel=1e-6)

    hp.sink_target.deactivate()
    before = [(v.value, v.fixed) for v in variables]
    hp.select_fidelity("cycle")
    assert [(v.value, v.fixed) for v in variables] == before
    assert cycle.ihx.active_fidelity == "high"
    assert degrees_of_freedom(m) == 0
    scale_model(m)
    hp.initialize(solver=solver)
    assert_conservation(hp)
    assert value(hp.electrical_power[0]) == pytest.approx(power, rel=1e-6)

    for unit in (cycle.ihx, cycle.expansion_valve):
        for name in ("low", "high"):
            unit.select_fidelity(name)
            assert degrees_of_freedom(m) == 0
            scale_model(m)
            assert check_optimal_termination(solver.solve(m))
            assert_conservation(hp)
