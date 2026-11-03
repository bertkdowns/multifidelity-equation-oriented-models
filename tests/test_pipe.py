"""Library pipe fidelity selection and mixed-inventory response."""
import json
import math
from pathlib import Path

import pyomo.environ as pyo
import pytest
from pyomo.util.check_units import assert_units_consistent

from multifidelity.model_language import build_model, required_initial_values, required_inputs, Library

EXAMPLES = Path(__file__).parents[1] / 'examples/model_language'


def selection(name):
    return json.loads((EXAMPLES / f'pipe_{name}.json').read_text())


def test_ideal_pipe_has_no_inventory_or_geometry(solver):
    chosen = selection('pass_through')
    assert set(required_inputs('pipe_flowsheet', chosen)) == {'pipe.inlet.flow', 'pipe.inlet.pressure', 'pipe.inlet.enthalpy'}
    assert required_initial_values('pipe_flowsheet', chosen) == {}
    m = build_model('pipe_flowsheet', chosen)
    b = m.fs.root.relationship.models.pipe.structs
    for field, value in [('flow', 2), ('pressure', 1e5), ('enthalpy', 1000)]:
        getattr(b.inlet, field).fix(value)
    pyo.assert_optimal_termination(solver.solve(m))
    for field in ['flow', 'pressure', 'enthalpy']:
        assert pyo.value(getattr(b.outlet, field)[0]) == pytest.approx(pyo.value(getattr(b.inlet, field)[0]))


@pytest.mark.parametrize('mode', ['steady', 'dynamic'])
@pytest.mark.parametrize('variable_density', [False, True])
def test_lumped_pipe_geometry_and_thermal_response(mode, variable_density, solver):
    chosen = selection('lumped')
    assert set(required_initial_values('pipe_flowsheet', chosen)) == {'pipe.contents.inventory.energy', 'pipe.contents.rates.mass'}
    library = Library()
    if variable_density:
        library.get('water_state_ph').relationships['constant_properties'].constraints['density'].rhs = (
            'parameters.density * (1 - parameters.thermal_expansion * '
            '(properties.temperature[t] - parameters.reference_temperature))')
    initial_temperature = 298.15 + (1000 - 104920.1198085 - (1e5-101325)/997)/4180
    mass = 997*(1-.000257*(initial_temperature-298.15)) if variable_density else 997
    m = build_model('pipe_flowsheet', chosen, library=library, mode=mode, domain_values={'time': [0, 10]} if mode == 'dynamic' else None)
    if mode == 'dynamic':
        pyo.TransformationFactory('dae.finite_difference').apply_to(m, wrt=m.fs.time, nfe=100, scheme='BACKWARD')
    b = m.fs.root.relationship.models.pipe.structs
    c = m.fs.root.relationship.models.pipe.relationship.models.contents.structs
    # One cubic metre, 997 kg water inventory; approximately 10 s residence time.
    c.parameters.length.fix(4 / math.pi)
    c.parameters.diameter.fix(1)
    b.inlet.flow.fix(100)
    b.inlet.pressure.fix(1e5)
    b.inlet.enthalpy.fix(2000)
    if mode == 'dynamic':
        c.inventory.energy[0].fix(mass*1000 - 1e5)
        c.rates.mass[0].fix(0)
    from multifidelity.model_language.standard.initialization import seed_affine_state
    contents = m.fs.root.relationship.models.pipe.relationship.models.contents
    for variable in m.component_data_objects(pyo.Var):
        if variable.value is None:
            variable.set_value(max(variable.lb or 1, 1))
    seed_affine_state(contents.relationship.models.contents_state, 1e5, 1000, flow=100)
    for t in m.fs.time:
        c.inventory.mass[t].set_value(mass)
        c.inventory.enthalpy[t].set_value(1000)
        if not c.inventory.energy[t].fixed: c.inventory.energy[t].set_value(mass*1000-1e5)
        c.outlet.pressure[t].set_value(1e5)
        c.outlet.flow[t].set_value(100)
        c.outlet.enthalpy[t].set_value(1000)
        b.outlet.pressure[t].set_value(1e5)
        b.outlet.flow[t].set_value(100)
        b.outlet.enthalpy[t].set_value(1000)
    assert_units_consistent(m)
    pyo.assert_optimal_termination(solver.solve(m))
    assert pyo.value(c.geometry.volume) == pytest.approx(1)
    for t in m.fs.time:
        if not variable_density or mode == 'steady':
            assert pyo.value(b.outlet.flow[t]) == pytest.approx(100)
        assert pyo.value(b.outlet.pressure[t]) == pytest.approx(1e5)
    expected = 2000 - 1000 / (1 + .1*100/997)**100 if mode == 'dynamic' else 2000
    if not variable_density or mode == 'steady':
        assert pyo.value(b.outlet.enthalpy[m.fs.time.last()]) == pytest.approx(expected, rel=1e-7)
    else:
        assert pyo.value(b.outlet.flow[m.fs.time.last()]) > 100
        for before, after in zip(list(m.fs.time), list(m.fs.time)[1:]):
            dt = after-before
            accumulation = (pyo.value(c.inventory.mass[after])-pyo.value(c.inventory.mass[before]))/dt
            assert accumulation == pytest.approx(100-pyo.value(b.outlet.flow[after]), abs=1e-7)
            energy = (pyo.value(c.inventory.energy[after])-pyo.value(c.inventory.energy[before]))/dt
            assert energy == pytest.approx(100*2000-pyo.value(b.outlet.flow[after]*b.outlet.enthalpy[after]), rel=1e-7)
