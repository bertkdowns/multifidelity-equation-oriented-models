"""Guesses never become specifications; native hooks preserve model fixity."""
import pytest
from pydantic import ValidationError
from pyomo.environ import Constraint, TransformationFactory, Var, units

from multifidelity.model_language import (
    InformationDocument, Library, ModelDocument, apply_specification,
    apply_starting_values, build_model, get_variable, initialize_custom_models,
)
from multifidelity.model_language.definitions import Variable


def record(id, path, value, unit='kPa', trust_rank=5):
    return dict(id=id, tag=id, variable_path=path, value=value, unit=unit,
                trust_rank=trust_rank, information_type='sensor_reading')


def test_defaults_broadcast_and_survive_discretization():
    library = Library()
    library.models['valve'].structs['inlet'].variables['pressure'].default = 200000
    library.models['valve'].structs['outlet'].variables['pressure'].default = None
    model = build_model('valve', {'relationship': 'isenthalpic'}, library=library,
                        mode='dynamic', domain_values={'time': [0, 1]})
    TransformationFactory('dae.finite_difference').apply_to(model, wrt=model.fs.time, nfe=4)
    assert all(v.value == 200000 and not v.fixed
               for v in get_variable(model, 'inlet.pressure').values())
    assert get_variable(model, 'outlet.pressure')[0].value is None


@pytest.mark.parametrize('guess', [float('nan'), float('inf'), -1, 11])
def test_invalid_default(guess):
    with pytest.raises(ValidationError):
        Variable(default=guess, bounds={'min': 0, 'max': 10})


def test_information_rank_units_exclusions_and_fixed_specifications():
    model = build_model('valve', {'relationship': 'isenthalpic'})
    info = InformationDocument([
        record('fixed', 'inlet.pressure', 200),
        record('out_low', 'outlet.pressure', 100),
        record('out_high', 'outlet.pressure', 150, trust_rank=8),
        record('held_out', 'outlet.pressure', 999, trust_rank=10),
        record('other_implementation', 'not_here.x', 10),
    ])
    spec = {'specifications': ['fixed']}
    apply_specification(model, spec, info)
    used = apply_starting_values(model, info, spec, excluded_record_ids=['held_out'])
    assert used == ['out_high']
    assert get_variable(model, 'outlet.pressure')[0].value == 150000
    assert not get_variable(model, 'outlet.pressure')[0].fixed
    assert get_variable(model, 'inlet.pressure')[0].value == 200000
    assert get_variable(model, 'inlet.pressure')[0].fixed


def test_information_validation_is_atomic():
    model = build_model('valve', {'relationship': 'isenthalpic'})
    get_variable(model, 'inlet.pressure')[0].set_value(123)
    info = InformationDocument([
        record('good', 'inlet.pressure', 200),
        record('bad', 'outlet.pressure', 1, unit='kg'),
    ])
    with pytest.raises(ValueError):
        apply_starting_values(model, info)
    assert get_variable(model, 'inlet.pressure')[0].value == 123


def custom(callback):
    library = Library()
    library.models['custom'] = ModelDocument.model_validate({
        'id': 'custom', 'structs': {
            'inlet': {'direction': 'input', 'variables': {'pressure': {'unit': 'Pa', 'default': 200000}}},
            'outlet': {'direction': 'output', 'variables': {'pressure': {'unit': 'Pa'}}},
        }, 'relationships': {'native': {'external': {'provider': 'test',
            'dependencies': {'outlet.pressure': ['inlet.pressure']}}}},
    })
    def provider(block, config):
        block.p = Var(units=units.kPa)
        block.q = Var(units=units.kPa)
        block.balance = Constraint(expr=block.q == block.p)
        return {'inlet.pressure': block.p, 'outlet.pressure': block.q}
    library.register_provider('test', provider, initializer=callback)
    return build_model('custom', {'relationship': 'native'}, library=library)


def test_callback_is_explicit_and_transfers_units_restoring_temporary_changes():
    calls = []
    def callback(block, config):
        calls.append(block.p.value)
        assert block.p.fixed
        block.q.fix(block.p.value)
        block.balance.deactivate()
    model = custom(callback)
    inlet = get_variable(model, 'inlet.pressure')
    inlet.fix(300000)
    assert calls == []
    assert len(initialize_custom_models(model)) == 1
    assert calls == [300]
    assert get_variable(model, 'outlet.pressure').value == 300000
    assert not get_variable(model, 'outlet.pressure').fixed
    native = model.fs.root.relationship.provider
    assert not native.p.fixed and not native.q.fixed
    assert native.balance.active
    assert inlet.fixed and inlet.value == 300000


def test_callback_failure_restores_values_and_fixity():
    def callback(block, config):
        block.p.fix(999)
        block.balance.deactivate()
        raise RuntimeError('failed')
    model = custom(callback)
    with pytest.raises(RuntimeError, match='failed'):
        initialize_custom_models(model)
    native = model.fs.root.relationship.provider
    assert native.p.value is None and not native.p.fixed
    assert native.balance.active
    assert get_variable(model, 'inlet.pressure').value == 200000


def test_callback_references_follow_model_clone():
    def callback(block, config):
        block.q.set_value(block.p.value)
    original = custom(callback)
    clone = original.clone()
    get_variable(clone, 'inlet.pressure').set_value(400000)
    initialize_custom_models(clone)
    assert get_variable(clone, 'outlet.pressure').value == 400000
    assert get_variable(original, 'outlet.pressure').value is None


def test_series_guesses_preserve_fixed_dynamic_initial_entry():
    model = build_model('valve', {'relationship': 'isenthalpic'},
                        mode='dynamic', domain_values={'time': [0, 1, 2]})
    family = get_variable(model, 'inlet.pressure')
    family[0].fix(200000)
    info = InformationDocument([
        {**record('profile', 'inlet.pressure', [100, 150, 180]), 'type': 'series'},
    ])
    assert apply_starting_values(model, info) == ['profile']
    assert [v.value for v in family.values()] == [200000, 150000, 180000]
    assert [v.fixed for v in family.values()] == [True, False, False]


def test_callback_receives_fixed_output_and_preserves_its_specification():
    def callback(block, config):
        assert block.q.fixed and block.q.value == 250
        block.p.set_value(block.q.value)
    model = custom(callback)
    outlet = get_variable(model, 'outlet.pressure')
    outlet.fix(250000)
    initialize_custom_models(model)
    assert get_variable(model, 'inlet.pressure').value == 250000
    assert outlet.fixed and outlet.value == 250000


def test_custom_callbacks_include_new_discretization_slices():
    from examples.custom_models.build import HERE, make_library
    model = build_model('pump_flowsheet', HERE / 'implementation.json',
                        library=make_library(), mode='dynamic',
                        domain_values={'time': [0, 1]})
    TransformationFactory('dae.finite_difference').apply_to(model, wrt=model.fs.time, nfe=4)
    completed = initialize_custom_models(model)
    assert len(completed) == 5
    density = get_variable(model, 'pump.properties.properties.density')
    assert len(density) == 5
    assert all(v.value == 997 and not v.fixed for v in density.values())
