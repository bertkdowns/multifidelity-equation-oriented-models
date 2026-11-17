"""Parameter slots preserve general structural meaning and editable pairs."""

import pytest
from pydantic import ValidationError
from pyomo.environ import Constraint, Var

from multifidelity.model_language import (
    ResourceDocument, BlockRegistry, BlockDefinition, ParameterDocument,
    apply_parameters, audit_fixations, build_model, canonical_inputs,
    get_variable, pair_parameters, select_parameters, parameter_slots,
)


def algebra(tmp_path, *, grid=False, mode="steady"):
    dimensions = ['time'] if grid else []
    registry = BlockRegistry(tmp_path)
    def variables(names):
        return {n: {'dimensions': dimensions, 'default': 1} for n in names}

    def equation(lhs, rhs):
        return dict(lhs=lhs + ('[t]' if grid else ''), rhs=rhs,
                    determines=lhs + ('[t]' if grid else ''),
                    **({'for_each': {'t': 'time'}} if grid else {}))
    registry.blocks['algebra'] = BlockDefinition.model_validate({
        'id': 'algebra', 'domains': {'time': {'kind': 'time'}} if grid else {},
        'structs': {
            'input': {'direction': 'input', 'variables': variables(['x', 'y', 'isolated'])},
            'output': {'direction': 'output', 'variables': variables(['a', 'b'])},
        }, 'formulations': {'equations': {'constraints': {
            'a': equation('output.a', 'input.x[t]' if grid else 'input.x'),
            'b': equation('output.b', 'input.x[t] + input.y[t]' if grid else 'input.x + input.y'),
        }}},
    })
    return build_model('algebra', {'formulation': 'equations'}, registry=registry,
                       domain_values={'time': [0, 10]} if grid else None, mode=mode)


def records(**paths):
    return ResourceDocument([dict(tag=i, resource_type='sensor_reading',
                                    variable_path=p, value=2, unit='dimensionless', trust_rank=10)
                                for i, p in paths.items()])


def test_manual_pair_is_portable_and_retains_equations(tmp_path):
    model = algebra(tmp_path)
    info = records(measurement='output.b')
    spec = ParameterDocument(parameters=['measurement'],
                                 replacements={'measurement': 'input.y'})
    assert ParameterDocument.from_json(spec.model_dump_json()) == spec
    equations = list(model.component_data_objects(Constraint))
    apply_parameters(model, spec, info)
    assert get_variable(model, 'output.b').fixed
    assert not get_variable(model, 'input.y').fixed
    assert list(model.component_data_objects(Constraint)) == equations
    assert parameter_slots(model) == [dict(canonical_input='input.y',
                                               variable_path='output.b', record_tag='measurement')]
    audit_fixations(model.clone())


@pytest.mark.parametrize('replacement,error', [
    (None, 'explicit replacement'),
    ('output.a', 'not an unsupplied input'),
    ('input.isolated', 'not structurally connected'),
    ('input.y', 'not a structurally admissible'),
])
def test_invalid_pair_does_not_mutate_values_or_slots(tmp_path, replacement, error):
    model = algebra(tmp_path)
    before = [(v.value, v.fixed) for v in model.component_data_objects(Var)]
    spec = dict(parameters=['measurement'])
    if replacement is not None:
        spec['replacements'] = {'measurement': replacement}
    with pytest.raises(ValueError, match=error):
        apply_parameters(model, spec, records(measurement='output.a'))
    assert [(v.value, v.fixed) for v in model.component_data_objects(Var)] == before
    assert parameter_slots(model) == []


def test_automatic_pairing_reassigns_for_a_later_direct_input(tmp_path):
    model = algebra(tmp_path)
    info = records(a='output.b', z='input.x')
    first = pair_parameters(model, {'parameters': ['a']}, info)
    assert first.replacements == {'a': 'input.x'}
    final = pair_parameters(model, {'parameters': ['a', 'z']}, info)
    assert final.replacements == {'a': 'input.y'}
    selection = select_parameters(model, info)
    assert selection.parameters.replacements == final.replacements
    assert selection.pairing_error is None
    apply_parameters(model, selection.parameters, info)
    assert get_variable(model, 'input.x').fixed
    assert get_variable(model, 'output.b').fixed
    assert not get_variable(model, 'input.y').fixed


def test_user_override_keeps_fixed_set_and_slot_exclusivity(tmp_path):
    info = records(a='output.b', direct='input.x', b='output.a')
    for slot in ['input.x', 'input.y']:
        model = algebra(tmp_path)
        apply_parameters(model, {'parameters': ['a'], 'replacements': {'a': slot}}, info)
        assert [p for p, v in model._model_language_variables.items() if v.fixed] == ['output.b']
        with pytest.raises(ValueError, match='already specified'):
            apply_parameters(model, {'parameters': ['b'], 'replacements': {'b': slot}}, info)
    with pytest.raises(ValueError, match='already specified'):
        apply_parameters(algebra(tmp_path), {'parameters': ['a', 'direct'],
                                               'replacements': {'a': 'input.x'}}, info)


def test_pairing_is_joint_and_ordered_candidates_do_not_steal_pinned_slots(tmp_path):
    model = algebra(tmp_path)
    info = records(b='output.b', a='output.a')
    spec = pair_parameters(model, {'parameters': ['b', 'a'],
                                     'replacements': {'a': 'input.x'}}, info)
    assert spec.replacements == {'b': 'input.y', 'a': 'input.x'}
    apply_parameters(model, spec, info)


def test_families_are_exchanged_as_whole_grids(tmp_path):
    model = algebra(tmp_path, grid=True)
    info = records(b='output.b')
    spec = pair_parameters(model, {'parameters': ['b']}, info)
    apply_parameters(model, spec, info)
    assert all(v.fixed for v in get_variable(model, 'output.b').values())
    assert all(not v.fixed for v in canonical_inputs(model)['input.x'].values())
    model.scalar = Var(initialize=1)
    # Scalar and trajectory do not become interchangeable just because both
    # belong to the same declared root model.
    model._model_language_variables['scalar'] = model.scalar
    with pytest.raises(ValueError, match='index domains'):
        apply_parameters(model, {'parameters': ['scalar'],
                                   'replacements': {'scalar': 'input.y'}}, records(scalar='scalar'))


def test_audit_detects_unmanaged_fixes_and_refixed_replaced_inputs(tmp_path):
    model = algebra(tmp_path)
    get_variable(model, 'output.a').fix(2)
    with pytest.raises(ValueError, match='explicit replacement'):
        audit_fixations(model)
    get_variable(model, 'output.a').unfix()
    apply_parameters(model, {'parameters': ['a'], 'replacements': {'a': 'input.x'}},
                        records(a='output.a'))
    get_variable(model, 'input.x').fix(2)
    with pytest.raises(ValueError, match='must remain free'):
        audit_fixations(model)


@pytest.mark.parametrize('data', [
    {'replacements': {'absent': 'input.x'}},
    {'parameters': ['a'], 'replacements': {'a': ''}},
    {'parameters': ['a', 'b'], 'replacements': {'a': 'input.x', 'b': 'input.x'}},
    {'initial_values': ['a'], 'replacements': {'a': 'input.x'}},
])
def test_replacement_catalog_shape_is_explicit(data):
    with pytest.raises(ValidationError):
        ParameterDocument.model_validate(data)


def test_locality_uses_occurrence_structure_and_saved_results_keep_pairs(tmp_path):
    from multifidelity.model_language import export_results, ResultsDocument
    registry = BlockRegistry(tmp_path)
    # Reuse an algebraic definition behind a hierarchy, without domain metadata.
    definition = {
        'id': 'leaf', 'structs': {
            'input': {'direction': 'input', 'variables': {'x': {}, 'y': {}}},
            'output': {'direction': 'output', 'variables': {'z': {}}},
        }, 'formulations': {'sum': {'constraints': {
            'sum': {'lhs': 'output.z', 'rhs': 'input.x + input.y', 'determines': 'output.z'}}}},
    }
    registry.blocks['leaf'] = BlockDefinition.model_validate(definition)
    registry.blocks['root'] = BlockDefinition.model_validate({
        'id': 'root', 'structs': {'feed': {'direction': 'input', 'variables': {'x': {}}}},
        'formulations': {'link': {'blocks': {'child': {'block': 'leaf'}}, 'constraints': {
            'feed': {'lhs': 'child.input.x', 'rhs': 'feed.x', 'determines': 'child.input.x'}}}},
    })
    model = build_model('root', {'formulation': 'link', 'subblocks': {'child': {'formulation': 'sum'}}}, registry=registry)
    info = records(value='child.output.z')
    spec = pair_parameters(model, {'parameters': ['value']}, info)
    assert spec.replacements == {'value': 'child.input.y'}
    assert not any(v.fixed for v in model.component_data_objects(Var))
    apply_parameters(model, spec, info)
    snapshot = export_results(model, parameters=spec)
    assert ResultsDocument.from_json(snapshot.model_dump_json()).parameters == spec
    assert parameter_slots(model.clone()) == parameter_slots(model)


def test_initial_slice_cannot_refill_a_replaced_operating_input(tmp_path):
    model = algebra(tmp_path, grid=True, mode='dynamic')
    info = records(operating='output.a', initial='input.x')
    with pytest.raises(ValueError, match='must remain free'):
        apply_parameters(model, {'parameters': ['operating'],
                                    'replacements': {'operating': 'input.x'},
                                    'initial_values': ['initial']}, info)
    assert not any(v.fixed for v in model.component_data_objects(Var))
    assert parameter_slots(model) == []


def test_edited_catalog_mapping_is_revalidated_before_application(tmp_path):
    model = algebra(tmp_path)
    spec = ParameterDocument(parameters=['a'], replacements={'a': 'input.x'})
    spec.replacements['absent'] = 'input.y'
    with pytest.raises(ValidationError, match='selected operating'):
        apply_parameters(model, spec, records(a='output.a'))
    assert not any(v.fixed for v in model.component_data_objects(Var))
