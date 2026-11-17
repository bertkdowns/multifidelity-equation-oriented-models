"""Selection must use equation independence, preserve context, and expose gaps."""

from pathlib import Path

from pyomo.environ import Constraint, Var

from multifidelity.model_language import (
    ResourceDocument, apply_parameters, build_model, get_variable,
    select_parameters,
)


EXAMPLE = Path(__file__).parents[1] / 'examples/parameters'


def valve():
    return build_model('valve', {'formulation': 'isenthalpic'})


def test_valve_selects_subset_without_mutating_model():
    model = valve()
    table = ResourceDocument.load_json(EXAMPLE / 'resources.json')
    before = [(v, v.value, v.fixed) for v in model.component_data_objects(Var)]
    result = select_parameters(model, table)
    assert result.complete
    assert (result.initial_deficiency, result.remaining_deficiency) == (4, 0)
    assert result.parameters.parameters == (
        'inlet_flow', 'pressure_measurement', 'inlet_enthalpy', 'valve_pressure_drop')
    assert all(v.value == value and v.fixed == fixed for v, value, fixed in before)
    assert len([d for d in result.decisions if not d['selected']]) == 4
    apply_parameters(model, result.parameters, table)
    assert select_parameters(model, table).complete


def test_outputs_can_replace_inputs_and_ties_are_deterministic():
    table = ResourceDocument.load_json(EXAMPLE / 'resources.json')
    records = [r.model_copy(update={'trust_rank': 10}) for r in table.records
               if r.tag != 'inlet_flow']
    first = select_parameters(valve(), ResourceDocument(records))
    second = select_parameters(valve(), ResourceDocument(reversed(records)))
    assert first.complete
    assert first.parameters == second.parameters
    assert 'outlet_flow_check' in first.parameters.parameters


def test_reserved_targets_and_insufficient_resources():
    table = ResourceDocument.load_json(EXAMPLE / 'resources.json')
    result = select_parameters(valve(), table,
                                  prediction_targets=['outlet.flow'],
                                  excluded_record_tags=['inlet_flow'])
    assert not result.complete
    assert result.remaining_deficiency == 1
    assert result.unresolved_variables
    assert 'outlet_flow_check' not in result.parameters.parameters


def test_isolated_variables_and_local_overconstraint_are_not_hidden():
    model = valve()
    model.isolated = Var()
    result = select_parameters(model, ResourceDocument([]))
    assert result.remaining_deficiency == 5
    assert 'isolated' in result.unresolved_variables
    model.extra = Constraint(expr=get_variable(model, 'inlet.flow')[0] == 1)
    model.duplicate = Constraint(expr=get_variable(model, 'inlet.flow')[0] == 2)
    result = select_parameters(model, ResourceDocument.load_json(EXAMPLE / 'resources.json'))
    assert not result.complete
    assert result.overconstrained_constraints
    assert not result.parameters.parameters


def test_incompatible_preferred_record_falls_back_and_setpoints_need_assumption():
    records = [dict(tag='bad', resource_type='sensor_reading',
                    variable_path='inlet.pressure', value=2, unit='kg', trust_rank=10),
               dict(tag='setpoint', resource_type='control_setpoint',
                    variable_path='inlet.pressure', value=200, unit='kPa', trust_rank=9),
               dict(tag='fallback', resource_type='assumption',
                    variable_path='inlet.pressure', value=190, unit='kPa', trust_rank=1)]
    table = ResourceDocument(records)
    result = select_parameters(valve(), table)
    assert result.parameters.parameters == ('fallback',)
    result = select_parameters(valve(), table, achieved_setpoint_tags=['setpoint'])
    assert result.parameters.parameters == ('setpoint',)


def test_family_trial_rejected_if_one_entry_is_already_determined():
    model = valve()
    model.profile = Var([0, 1])
    model.profile_equation = Constraint(expr=model.profile[0] == 1)
    model._model_language_variables['profile'] = model.profile
    table = ResourceDocument([dict(
        tag='profile', resource_type='assumption',
        variable_path='profile', value=1, unit='dimensionless', trust_rank=10)])
    result = select_parameters(model, table)
    assert not result.parameters.parameters
    assert result.remaining_deficiency == result.initial_deficiency == 5
    assert 'overconstraint' in result.decisions[0]['reason']
    assert not model.profile[0].fixed and not model.profile[1].fixed
