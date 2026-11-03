"""Selection must use equation independence, preserve context, and expose gaps."""

from pathlib import Path

from pyomo.environ import Constraint, Var

from multifidelity.model_language import (
    InformationDocument, apply_specification, build_model, get_variable,
    select_specification,
)


EXAMPLE = Path(__file__).parents[1] / 'examples/specification'


def valve():
    return build_model('valve', {'relationship': 'isenthalpic'})


def test_valve_selects_subset_without_mutating_model():
    model = valve()
    table = InformationDocument.load_json(EXAMPLE / 'information.json')
    before = [(v, v.value, v.fixed) for v in model.component_data_objects(Var)]
    result = select_specification(model, table)
    assert result.complete
    assert (result.initial_deficiency, result.remaining_deficiency) == (4, 0)
    assert result.specification.specifications == (
        'inlet_flow', 'pressure_measurement', 'inlet_enthalpy', 'valve_pressure_drop')
    assert all(v.value == value and v.fixed == fixed for v, value, fixed in before)
    assert len([d for d in result.decisions if not d['selected']]) == 4
    apply_specification(model, result.specification, table)
    assert select_specification(model, table).complete


def test_outputs_can_replace_inputs_and_ties_are_deterministic():
    table = InformationDocument.load_json(EXAMPLE / 'information.json')
    records = [r.model_copy(update={'trust_rank': 10}) for r in table.records
               if r.id != 'inlet_flow']
    first = select_specification(valve(), InformationDocument(records))
    second = select_specification(valve(), InformationDocument(reversed(records)))
    assert first.complete
    assert first.specification == second.specification
    assert 'outlet_flow_check' in first.specification.specifications


def test_reserved_targets_and_insufficient_information():
    table = InformationDocument.load_json(EXAMPLE / 'information.json')
    result = select_specification(valve(), table,
                                  prediction_targets=['outlet.flow'],
                                  excluded_record_ids=['inlet_flow'])
    assert not result.complete
    assert result.remaining_deficiency == 1
    assert result.unresolved_variables
    assert 'outlet_flow_check' not in result.specification.specifications


def test_isolated_variables_and_local_overconstraint_are_not_hidden():
    model = valve()
    model.isolated = Var()
    result = select_specification(model, InformationDocument([]))
    assert result.remaining_deficiency == 5
    assert 'isolated' in result.unresolved_variables
    model.extra = Constraint(expr=get_variable(model, 'inlet.flow')[0] == 1)
    model.duplicate = Constraint(expr=get_variable(model, 'inlet.flow')[0] == 2)
    result = select_specification(model, InformationDocument.load_json(EXAMPLE / 'information.json'))
    assert not result.complete
    assert result.overconstrained_constraints
    assert not result.specification.specifications


def test_incompatible_preferred_record_falls_back_and_setpoints_need_assumption():
    records = [dict(id='bad', tag='a', information_type='sensor_reading',
                    variable_path='inlet.pressure', value=2, unit='kg', trust_rank=10),
               dict(id='setpoint', tag='b', information_type='control_setpoint',
                    variable_path='inlet.pressure', value=200, unit='kPa', trust_rank=9),
               dict(id='fallback', tag='c', information_type='assumption',
                    variable_path='inlet.pressure', value=190, unit='kPa', trust_rank=1)]
    table = InformationDocument(records)
    result = select_specification(valve(), table)
    assert result.specification.specifications == ('fallback',)
    result = select_specification(valve(), table, achieved_setpoint_ids=['setpoint'])
    assert result.specification.specifications == ('setpoint',)


def test_family_trial_rejected_if_one_entry_is_already_determined():
    model = valve()
    model.profile = Var([0, 1])
    model.profile_equation = Constraint(expr=model.profile[0] == 1)
    model._model_language_variables['profile'] = model.profile
    table = InformationDocument([dict(
        id='profile', tag='p', information_type='assumption',
        variable_path='profile', value=1, unit='dimensionless', trust_rank=10)])
    result = select_specification(model, table)
    assert not result.specification.specifications
    assert result.remaining_deficiency == result.initial_deficiency == 5
    assert 'overconstraint' in result.decisions[0]['reason']
    assert not model.profile[0].fixed and not model.profile[1].fixed
