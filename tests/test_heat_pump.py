"""Aggregate heat-pump prediction and rating through the public interface."""

import pytest
from idaes.core.util.model_statistics import degrees_of_freedom
from pyomo.environ import check_optimal_termination, value
from pyomo.util.check_units import assert_units_consistent

from examples.heat_pump import build_model


def test_specification_and_units():
    m = build_model()
    assert degrees_of_freedom(m) == 0
    assert_units_consistent(m)


def test_power_prediction_and_rating(solver):
    m = build_model()
    hp = m.fs.hp
    hp.initialize(solver=solver)
    assert check_optimal_termination(solver.solve(m))
    heating = value(hp.heating_duty[0])
    power = value(hp.electrical_power[0])
    cooling = value(hp.cooling_duty[0])
    assert heating > 0
    assert power == pytest.approx(heating / 3)
    assert cooling == pytest.approx(heating - power)
    assert value(hp.source_outlet.temperature[0]) == pytest.approx(300 - 20 / 3)
    assert value(hp.source_outlet.flow_mass[0]) == pytest.approx(1)
    assert value(hp.sink_outlet.flow_mass[0]) == pytest.approx(1)
    assert value(hp.source_outlet.pressure[0]) == pytest.approx(300000)
    assert value(hp.sink_outlet.pressure[0]) == pytest.approx(300000)
    hp.sink_outlet.temperature.unfix()
    hp.electrical_power.fix(power)
    assert degrees_of_freedom(m) == 0
    hp.initialize(solver=solver)
    assert value(hp.sink_outlet.temperature[0]) == pytest.approx(330)
    assert hp.electrical_power[0].fixed
    assert not hp.sink_outlet.temperature[0].fixed
