"""Integration contracts for interchangeable liquid-water property equations."""

import pytest

from idaes.core import FlowsheetBlock
from idaes.core.util.model_statistics import degrees_of_freedom
from idaes.models.properties.iapws95 import iapws95_available
from pyomo.environ import (
    ConcreteModel,
    Constraint,
    Var,
    check_optimal_termination,
    units as u,
    value,
)
from pyomo.util.check_units import assert_units_consistent

from multifidelity import (
    HeatExchanger,
    HelmholtzWater,
    LinearWater,
    WaterParameterBlock,
)


def state_model(builders):
    m = ConcreteModel()
    m.fs = FlowsheetBlock(dynamic=False)
    m.fs.water = WaterParameterBlock(fidelities=builders)
    m.fs.states = m.fs.water.build_state_block([0], defined_state=True)
    state = m.fs.states[0]
    state.flow_mass.fix(1)
    state.temperature.fix(298.15)
    state.pressure.fix(101325)
    return m, state


def test_linear_water_has_constant_heat_capacity_and_affine_properties(solver):
    m, state = state_model({"linear": LinearWater()})
    values = []
    for i in range(3):
        state.temperature.fix(298.15 + 10 * i)
        state.initialize(solver=solver)
        assert check_optimal_termination(solver.solve(m))
        assert value(state.cp_mass) == pytest.approx(4180)
        values.append(
            [
                value(prop)
                for prop in (state.enth_mass, state.entr_mass, state.dens_mass)
            ]
        )
    for j in range(3):
        assert values[2][j] - values[1][j] == pytest.approx(values[1][j] - values[0][j])
    assert values[1][0] - values[0][0] == pytest.approx(4180 * 10)
    pressure_values = []
    for p in (101325, 301325, 501325):
        state.pressure.fix(p)
        state.initialize(solver=solver)
        pressure_values.append(
            [
                value(prop)
                for prop in (state.enth_mass, state.entr_mass, state.dens_mass)
            ]
        )
    for j in range(3):
        assert pressure_values[2][j] - pressure_values[1][j] == pytest.approx(
            pressure_values[1][j] - pressure_values[0][j]
        )
    assert degrees_of_freedom(m) == 0
    assert_units_consistent(m)


@pytest.mark.skipif(
    not iapws95_available(), reason="IDAES Helmholtz extensions required"
)
def test_water_fidelity_round_trip_preserves_external_property_connections(solver):
    m, state = state_model({"linear": LinearWater(), "helmholtz": HelmholtzWater()})
    state.temperature.fix(320)
    state.pressure.fix(300000)
    m.enthalpy_flow = Var(initialize=2e5, units=u.W)
    m.connection = Constraint(
        expr=m.enthalpy_flow == state.get_enthalpy_flow_terms("Liq")
    )
    public = (
        state.flow_mass,
        state.temperature,
        state.pressure,
        state.enth_mass,
        state.entr_mass,
        state.dens_mass,
        state.cp_mass,
    )
    flags = [v.fixed for v in public]
    outputs = []
    for name in ("linear", "helmholtz", "linear"):
        guesses = [v.value for v in public]
        state.select_fidelity(name)
        assert [v.value for v in public] == guesses
        assert [v.fixed for v in public] == flags
        assert degrees_of_freedom(m) == 0
        state.initialize(solver=solver)
        assert check_optimal_termination(solver.solve(m))
        assert [v.fixed for v in public] == flags
        assert value(m.enthalpy_flow) == pytest.approx(
            value(state.flow_mass * state.enth_mass)
        )
        outputs.append(value(state.enth_mass))
        assert 980 < value(state.dens_mass) < 1000
        assert 4100 < value(state.cp_mass) < 4300
    assert outputs[1] == pytest.approx(196421.3646, rel=1e-6)
    assert outputs[0] == pytest.approx(outputs[1], rel=1e-2)
    assert outputs[2] == pytest.approx(outputs[0], rel=1e-9)
    assert_units_consistent(m)


@pytest.mark.parametrize("property_fidelity", ["linear", "helmholtz"])
def test_water_properties_work_in_both_exchanger_formulations(
    property_fidelity, solver
):
    if property_fidelity == "helmholtz" and not iapws95_available():
        pytest.skip("IDAES Helmholtz extensions required")
    builder = LinearWater() if property_fidelity == "linear" else HelmholtzWater()
    m = ConcreteModel()
    m.fs = FlowsheetBlock(dynamic=False)
    m.fs.water = WaterParameterBlock(fidelities={property_fidelity: builder})
    m.fs.hx = HeatExchanger(
        hot_side_property_package=m.fs.water, cold_side_property_package=m.fs.water
    )
    h = m.fs.hx
    h.area.fix(10)
    h.U.fix(500)
    h.length.fix(5)
    for port, flow, T in ((h.hot_inlet, 1, 370), (h.cold_inlet, 1.2, 300)):
        port.flow_mass.fix(flow)
        port.temperature.fix(T)
        port.pressure.fix(300000)
    for name in ("lumped", "distributed", "lumped"):
        h.select_fidelity(name)
        assert degrees_of_freedom(m) == 0
        h.initialize(solver=solver)
        assert check_optimal_termination(solver.solve(m))
        hot_loss = value(
            h.hot_inlet_state[0].get_enthalpy_flow_terms("Liq")
            - h.hot_outlet_state[0].get_enthalpy_flow_terms("Liq")
        )
        assert value(h.heat_duty[0]) > 0
        assert value(h.heat_duty[0]) == pytest.approx(hot_loss, rel=1e-7)
        assert value(h.hot_outlet.flow_mass[0]) == pytest.approx(1)
        assert value(h.cold_outlet.flow_mass[0]) == pytest.approx(1.2)
    assert_units_consistent(m)
