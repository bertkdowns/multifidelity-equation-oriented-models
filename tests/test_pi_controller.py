"""Ideal tracking and PI construction, equilibrium, and integral evolution."""

import pytest
from pyomo.environ import TransformationFactory, Var, value
from pyomo.util.calc_var_value import calculate_variable_from_constraint
from pyomo.util.check_units import assert_units_consistent

from multifidelity.model_language import build_model, required_inputs, required_initial_values


IDEAL = {'relationship': 'ideal_tracking'}
PI = {'relationship': 'pi', 'submodels': {'integral': {'relationship': 'integrate'}}}


def test_ideal_tracking_has_implicit_output_and_no_tuning():
    model = build_model('pi_controller', IDEAL)
    root = model.fs.root
    root.structs.signals.setpoint[0].set_value(0.6)
    root.structs.signals.process_variable[0].set_value(0.6)
    assert value(root.relationship.constraints.tracking[0].body) == pytest.approx(0)
    assert not root.structs.output.value[0].fixed
    assert set(required_inputs('pi_controller', IDEAL)) == {
        'signals.setpoint', 'signals.process_variable'}
    assert required_initial_values('pi_controller', IDEAL) == {}


def test_pi_steady_equilibrium_retains_integral_output():
    model = build_model('pi_controller', PI)
    root = model.fs.root
    child = root.relationship.models.integral
    root.structs.signals.setpoint[0].set_value(0.6)
    root.structs.signals.process_variable[0].set_value(0.6)
    child.structs.signal.error[0].set_value(0)
    child.structs.tuning.kp.set_value(2)
    child.structs.tuning.ki.set_value(0.5)
    child.structs.tuning.bias.set_value(0.1)
    child.structs.state.integral[0].set_value(0.8)
    calculate_variable_from_constraint(root.structs.output.value[0], root.relationship.constraints.control[0])
    assert value(root.structs.output.value[0]) == pytest.approx(0.5)
    assert set(required_initial_values('pi_controller', PI)) == {'integral.state.integral'}
    assert set(required_inputs('pi_controller', PI)) == {
        'signals.setpoint', 'signals.process_variable', 'integral.tuning.kp',
        'integral.tuning.ki', 'integral.tuning.bias'}
    assert all(not v.fixed for v in model.component_data_objects(Var))
    assert_units_consistent(model)


def test_dynamic_pi_integrates_constant_error():
    model = build_model('pi_controller', PI, mode='dynamic', domain_values={'time': [0, 2]})
    TransformationFactory('dae.finite_difference').apply_to(model, wrt=model.fs.time, nfe=2, scheme='BACKWARD')
    root = model.fs.root
    child = root.relationship.models.integral
    child.structs.tuning.kp.set_value(2)
    child.structs.tuning.ki.set_value(0.5)
    child.structs.tuning.bias.set_value(0.1)
    # Constant error 0.2 gives I(t)=0.2*t and u(t)=0.5+0.1*t.
    for t in model.fs.time:
        root.structs.signals.setpoint[t].set_value(0.6)
        root.structs.signals.process_variable[t].set_value(0.4)
        child.structs.signal.error[t].set_value(0.2)
        child.structs.state.integral[t].set_value(0.2 * t)
        calculate_variable_from_constraint(root.structs.output.value[t], root.relationship.constraints.control[t])
        assert value(root.structs.output.value[t]) == pytest.approx(0.5 + 0.1 * t)
    # Validate the actual derivative bindings and discretization equations.
    from pyomo.environ import Constraint
    for t in model.fs.time:
        child.relationship.derivatives.integral.coordinate_rate[t].set_value(0.2)
    for constraint in model.component_data_objects(Constraint, active=True):
        assert value(constraint.body) == pytest.approx(value(constraint.lower), abs=1e-10)
    assert_units_consistent(model)
