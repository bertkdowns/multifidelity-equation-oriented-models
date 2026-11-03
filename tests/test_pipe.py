"""Library pipe fidelity selection and mixed-inventory response."""
import json
import math
from pathlib import Path

import pyomo.environ as pyo
import pytest
from pyomo.util.check_units import assert_units_consistent

from multifidelity.model_language import build_model, required_initial_values, required_inputs

EXAMPLES = Path(__file__).parents[1] / 'examples/model_language'


def selection(name):
    return json.loads((EXAMPLES / f'pipe_{name}.json').read_text())


def test_ideal_pipe_has_no_inventory_or_geometry(solver):
    chosen = selection('pass_through')
    assert set(required_inputs('pipe', chosen)) == {'inlet.flow', 'inlet.pressure', 'inlet.enthalpy'}
    assert required_initial_values('pipe', chosen) == {}
    m = build_model('pipe', chosen)
    b = m.fs.root.structs
    for field, value in [('flow', 2), ('pressure', 1e5), ('enthalpy', 1000)]:
        getattr(b.inlet, field).fix(value)
    pyo.assert_optimal_termination(solver.solve(m))
    for field in ['flow', 'pressure', 'enthalpy']:
        assert pyo.value(getattr(b.outlet, field)[0]) == pytest.approx(pyo.value(getattr(b.inlet, field)[0]))


@pytest.mark.parametrize('mode', ['steady', 'dynamic'])
def test_lumped_pipe_geometry_and_thermal_response(mode, solver):
    chosen = selection('lumped')
    assert set(required_initial_values('pipe', chosen)) == {'contents.inventory.energy'}
    m = build_model('pipe', chosen, mode=mode, domain_values={'time': [0, 10]} if mode == 'dynamic' else None)
    if mode == 'dynamic':
        pyo.TransformationFactory('dae.finite_difference').apply_to(m, wrt=m.fs.time, nfe=100, scheme='BACKWARD')
    b = m.fs.root.structs
    c = m.fs.root.relationship.models.contents.structs
    # One cubic metre, 1000 kg inventory; flow gives a 10 s residence time.
    c.parameters.length.fix(4 / math.pi)
    c.parameters.diameter.fix(1)
    c.parameters.density.fix(1000)
    b.inlet.flow.fix(100)
    b.inlet.pressure.fix(1e5)
    b.inlet.enthalpy.fix(2000)
    if mode == 'dynamic':
        c.inventory.energy[0].fix(1e6)
    assert_units_consistent(m)
    pyo.assert_optimal_termination(solver.solve(m))
    assert pyo.value(c.geometry.volume) == pytest.approx(1)
    for t in m.fs.time:
        assert pyo.value(b.outlet.flow[t]) == pytest.approx(100)
        assert pyo.value(b.outlet.pressure[t]) == pytest.approx(1e5)
    expected = 2000 - 1000 / 1.01**100 if mode == 'dynamic' else 2000
    assert pyo.value(b.outlet.enthalpy[m.fs.time.last()]) == pytest.approx(expected, rel=1e-7)
