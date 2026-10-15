"""Integration contracts, exercised through the exchanger's public interface."""

import pytest

from idaes.core.solvers import get_solver
from idaes.core.util.exceptions import InitializationError
from idaes.core.util.model_statistics import degrees_of_freedom
from idaes.models.unit_models import Feed
from pyomo.environ import TransformationFactory, check_optimal_termination, value
from pyomo.network import Arc
from pyomo.util.check_units import assert_units_consistent

from examples.heat_exchanger import build_model


@pytest.fixture
def solver():
    solver = get_solver("ipopt", options={"tol": 1e-8, "max_iter": 500})
    if not solver.available(False):
        pytest.skip("IPOPT is required for numerical integration tests")
    return solver


def connected_model():
    m = build_model()
    h = m.fs.hx
    m.fs.feed = Feed(property_package=m.fs.properties)
    for name, variable in h.hot_inlet.vars.items():
        for key, v in variable.items():
            m.fs.feed.outlet.vars[name][key].fix(value(v))
            v.unfix()
    m.fs.connection = Arc(source=m.fs.feed.outlet, destination=h.hot_inlet)
    TransformationFactory("network.expand_arcs").apply_to(m)
    return m


def public_variables(h):
    yield h.area
    yield h.length
    yield from h.U.values()
    for port in (h.hot_inlet, h.hot_outlet, h.cold_inlet, h.cold_outlet):
        for variable in port.vars.values():
            yield from variable.values()


def enthalpy(state):
    return value(sum(state.get_enthalpy_flow_terms(p) for p in state.phase_list))


@pytest.mark.parametrize("connected", [False, True])
def test_round_trip_preserves_specifications_and_physics(connected, solver):
    m = connected_model() if connected else build_model()
    h = m.fs.hx
    flags = [(v, v.fixed) for v in public_variables(h)]
    duties = []
    for name in ("lumped", "distributed", "lumped"):
        before = [(v, v.value) for v in public_variables(h)]
        h.select_fidelity(name)
        assert h.active_fidelity == name
        assert all(v.value == guess for v, guess in before)
        # Both formulations expose the same remaining design freedom.
        h.area.unfix()
        h.U.unfix()
        assert degrees_of_freedom(m) == 2
        h.area.fix()
        h.U.fix()
        assert degrees_of_freedom(m) == 0
        assert_units_consistent(m)
        h.initialize(solver=solver)
        assert all(v.fixed == flag for v, flag in flags)
        assert check_optimal_termination(solver.solve(m))
        assert value(h.hot_inlet.temperature[0]) == pytest.approx(370)
        assert 300 < value(h.hot_outlet.temperature[0]) < 370
        assert 300 < value(h.cold_outlet.temperature[0]) < 370
        hot_loss = enthalpy(h.hot_inlet_state[0]) - enthalpy(h.hot_outlet_state[0])
        cold_gain = enthalpy(h.cold_outlet_state[0]) - enthalpy(h.cold_inlet_state[0])
        duties.append(value(h.heat_duty[0]))
        assert duties[-1] > 0
        assert hot_loss == pytest.approx(cold_gain, rel=1e-7)
        assert duties[-1] == pytest.approx(cold_gain, rel=1e-10)
    assert duties[0] == pytest.approx(270768.3, rel=1e-5)
    assert duties[1] == pytest.approx(duties[0], rel=1e-3)
    assert duties[2] == pytest.approx(duties[0], rel=1e-8)


@pytest.mark.parametrize("name", ["lumped", "distributed"])
def test_initialization_failure_leaves_connected_model_usable(name, solver):
    m = connected_model()
    h = m.fs.hx
    h.select_fidelity(name)
    flags = [(v, v.fixed) for v in public_variables(h)]
    with pytest.raises(InitializationError):
        h.initialize(solver="ipopt", optarg={"max_iter": 0})
    assert h.active_fidelity == name
    assert all(v.fixed == flag for v, flag in flags)
    assert degrees_of_freedom(m) == 0
    h.initialize(solver=solver)
    assert check_optimal_termination(solver.solve(m))
    assert value(h.heat_duty[0]) > 0
