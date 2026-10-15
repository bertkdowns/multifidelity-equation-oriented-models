import pytest
from pyomo.common.collections import ComponentSet
from pyomo.core.expr.visitor import identify_variables
from pyomo.environ import Constraint, Var, value, check_optimal_termination, TransformationFactory
from pyomo.network import Arc
from pyomo.util.check_units import assert_units_consistent
from idaes.core.solvers import get_solver
from idaes.core.util.model_statistics import degrees_of_freedom
from idaes.models.unit_models import Feed
from idaes.models.unit_models.heat_exchanger import HeatExchangerData
from idaes.models.unit_models.heat_exchanger_1D import HeatExchanger1DData
from example import build_model


def test_exclusive_activation_and_shared_interface():
    m = build_model(finite_elements=2)
    h = m.fs.hx
    assert isinstance(h.fidelity_1, HeatExchangerData)
    assert isinstance(h.fidelity_2, HeatExchanger1DData)
    ports = tuple(getattr(h, n) for n in ['hot_side_inlet', 'cold_side_outlet'])
    for level in (h.fidelity_2, h.fidelity_1, h.fidelity_2):
        level.activate()
        assert h.active_fidelity is level
        assert sum(x.active for x in h.levels) == 1
        assert degrees_of_freedom(m) == 0
        inactive = next(x for x in h.levels if x is not level)
        private = ComponentSet(inactive.component_data_objects(Var))
        for con in m.component_data_objects(Constraint, active=True):
            assert all(v not in private for v in identify_variables(con.body))
        assert h.hot_side_inlet is ports[0]
        assert h.cold_side_outlet is ports[1]
    with pytest.raises(RuntimeError):
        h.active_fidelity.deactivate()
    with pytest.raises(ValueError):
        h.select_fidelity(3)
    assert h.area.fixed
    assert h.overall_heat_transfer_coefficient[0].fixed
    assert_units_consistent(m)


def test_clone_owns_its_selector():
    m = build_model(finite_elements=2)
    other = m.clone()
    other.fs.hx.fidelity_2.activate()
    assert other.fs.hx.active_fidelity is other.fs.hx.fidelity_2
    assert m.fs.hx.active_fidelity is m.fs.hx.fidelity_1


def test_initializer_restores_interface_and_fixations_on_failure(monkeypatch):
    m = build_model(finite_elements=2)
    h = m.fs.hx
    for level in h.levels:
        level.activate()
        before = [(v, v.fixed) for v in level.component_data_objects(Var)]
        constraints = [(c, c.active) for c in level.component_data_objects(Constraint)]
        def fail(**kwargs):
            assert not level.interface.active
            assert level.area.fixed
            next(level.component_data_objects(Var)).unfix()
            constraints[0][0].deactivate()
            raise RuntimeError('simulated solver failure')
        monkeypatch.setattr(level, 'initialize', fail)
        with pytest.raises(RuntimeError, match='simulated solver failure'):
            h.initialize()
        assert level.interface.active
        assert all(v.fixed == flag for v, flag in before)
        assert all(c.active == flag for c, flag in constraints)
        assert h.active_fidelity is level


def _solver():
    solver = get_solver('ipopt', options={'tol': 1e-8, 'max_iter': 500})
    if not solver.available(False):
        pytest.skip('IPOPT is required for numerical integration tests')
    return solver


def _enthalpy(states, t=0):
    state = states[t]
    return value(sum(state.get_enthalpy_flow_terms(p) for p in state.phase_list))


def test_round_trip_solves_and_conserves_energy():
    solver = _solver()
    m = build_model(finite_elements=6)
    h = m.fs.hx
    duties = []
    for level in (h.fidelity_1, h.fidelity_2, h.fidelity_1):
        level.activate()
        h.initialize(solver='ipopt', optarg={'tol': 1e-6})
        assert check_optimal_termination(solver.solve(m))
        duties.append(value(h.heat_duty[0]))
        assert 300 < value(h.cold_side_outlet.temperature[0]) < 370
        assert 300 < value(h.hot_side_outlet.temperature[0]) < 370
        if level is h.fidelity_1:
            hot = level.hot_side
            cold = level.cold_side
            qh = _enthalpy(hot.properties_in) - _enthalpy(hot.properties_out)
            qc = _enthalpy(cold.properties_out) - _enthalpy(cold.properties_in)
        else:
            hot = level.hot_side.properties
            cold = level.cold_side.properties
            def enthalpy(state):
                return value(sum(state.get_enthalpy_flow_terms(p) for p in state.phase_list))
            qh = enthalpy(hot[0, 0]) - enthalpy(hot[0, 1])
            qc = enthalpy(cold[0, 0]) - enthalpy(cold[0, 1])
        assert qh == pytest.approx(qc, rel=2e-6)
        assert duties[-1] == pytest.approx(qc, rel=1e-7)
    assert duties[0] == pytest.approx(duties[2], rel=1e-8)
    assert duties[1] == pytest.approx(duties[0], rel=1e-3)


def test_upstream_arc_survives_switch():
    solver = _solver()
    m = build_model(finite_elements=3)
    h = m.fs.hx
    m.fs.feed = Feed(property_package=m.fs.properties)
    for name, variable in h.hot_side_inlet.vars.items():
        source = m.fs.feed.outlet.vars[name]
        for key, v in variable.items():
            source[key].fix(value(v))
            v.unfix()
    m.fs.connection = Arc(source=m.fs.feed.outlet, destination=h.hot_side_inlet)
    TransformationFactory('network.expand_arcs').apply_to(m)
    for level in h.levels:
        level.activate()
        assert degrees_of_freedom(m) == 0
        h.initialize(solver='ipopt')
        assert check_optimal_termination(solver.solve(m))
        assert value(h.hot_side_inlet.temperature[0]) == pytest.approx(370)
