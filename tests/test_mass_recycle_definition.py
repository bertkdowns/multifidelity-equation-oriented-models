"""A recycle definition substitutes a separate flow without defining it twice."""
from pyomo.environ import Constraint, value
from pyomo.core.expr.visitor import identify_variables
from pyomo.util.check_units import assert_units_consistent
from multifidelity.model_language import build_model, get_variable


def test_flow_comes_from_separate_struct_and_standard_inlet_flow_is_unused():
    model = build_model('mass_recycle_definition', {'relationship': 'define'},
                        domain_values={'time': [0, 10]})
    assert_units_consistent(model)
    for t in model.fs.time:
        for path, number in {
            'inlet.flow': 99, 'inlet.pressure': 200000, 'inlet.enthalpy': 400000,
            'flow_definition.flow': 2, 'outlet.flow': 2,
            'outlet.pressure': 200000, 'outlet.enthalpy': 400000,
        }.items():
            get_variable(model, path)[t].set_value(number)
        unused = get_variable(model, 'inlet.flow')[t]
        for c in model.fs.root.relationship.component_data_objects(Constraint):
            assert all(v is not unused for v in identify_variables(c.body))
    for c in model.fs.root.relationship.component_data_objects(Constraint):
        assert value(c.body) == value(c.lower)
