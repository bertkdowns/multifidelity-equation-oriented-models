"""Local closures are temporary; parents solve the original coupled equations."""
from types import SimpleNamespace

import pytest
from pyomo.environ import Constraint, Var
from pyomo.opt import SolverStatus, TerminationCondition

from multifidelity.model_language import (
    InformationDocument, Library, ModelDocument,
    build_model, get_variable, initialize_model,
)


def tiny_library(tmp_path, *, recycle=False):
    library = Library(tmp_path)
    library.models['leaf'] = ModelDocument.model_validate({
        'id': 'leaf', 'structs': {
            'inlet': {'direction': 'input', 'variables': {'x': {'default': 1}}},
            'outlet': {'direction': 'output', 'variables': {'y': {}}},
        }, 'relationships': {'linear': {'constraints': {
            'balance': {'lhs': 'outlet.y', 'rhs': '0.5 * inlet.x + 1' if recycle else '2 * inlet.x',
                        'determines': 'outlet.y'},
        }}},
    })
    # Different field names require explicit equations, rather than a connection.
    connections = {}
    equations = {
        'middle': {'lhs': 'b.inlet.x', 'rhs': 'a.outlet.y', 'determines': 'b.inlet.x'},
        'export': {'lhs': 'outlet.y', 'rhs': 'b.outlet.y', 'determines': 'outlet.y'},
        'feed': {'lhs': 'a.inlet.x', 'rhs': 'b.outlet.y + inlet.x' if recycle else 'inlet.x',
                 'determines': 'a.inlet.x'},
    }
    library.models['plant'] = ModelDocument.model_validate({
        'id': 'plant', 'structs': {
            'inlet': {'direction': 'input', 'variables': {'x': {'default': 3}}},
            'outlet': {'direction': 'output', 'variables': {'y': {}}},
        }, 'relationships': {'flowsheet': {
            'models': {'a': {'model': 'leaf'}, 'b': {'model': 'leaf'}},
            'connections': connections, 'constraints': equations,
        }},
    })
    return library


def build_plant(tmp_path, *, recycle=False):
    return build_model('plant', {'relationship': 'flowsheet', 'submodels': {
        'a': {'relationship': 'linear'}, 'b': {'relationship': 'linear'},
    }}, library=tiny_library(tmp_path, recycle=recycle))


@pytest.mark.parametrize('recycle,feed,expected', [(False, 3, 12), (True, 1, 7/3)])
def test_parent_reconciles_child_guesses_and_recycles(tmp_path, solver, recycle, feed, expected):
    model = build_plant(tmp_path, recycle=recycle)
    get_variable(model, 'inlet.x').fix(feed)
    result = initialize_model(model, solver=solver)
    assert result.success
    assert [s.model_path for s in result.stages] == ['a', 'b', 'plant']
    assert [len(s.temporary_fixes) for s in result.stages] == [1, 1, 0]
    assert get_variable(model, 'outlet.y').value == pytest.approx(expected)
    assert not get_variable(model, 'a.inlet.x').fixed
    assert not get_variable(model, 'b.inlet.x').fixed
    assert get_variable(model, 'inlet.x').fixed
    assert get_variable(model, 'inlet.x').value == feed
    assert all(s.status == 'initialized' for s in result.stages)
    assert result.stages[-1].solver_termination == 'optimal'


def test_root_is_not_closed_with_guessed_operating_specs(tmp_path, solver):
    model = build_plant(tmp_path)
    result = initialize_model(model, solver=solver)
    assert not result.success and result.failed_model == 'plant'
    root = result.stages[-1]
    assert root.status == 'underconstrained' and root.remaining_deficiency == 1
    assert root.temporary_fixes == []
    assert all(not v.fixed for v in model.component_data_objects(Var))
    assert get_variable(model, 'a.outlet.y').value == pytest.approx(2)


def test_missing_boundary_guess_diagnoses_without_fixing_internal_variables(tmp_path, solver):
    model = build_plant(tmp_path)
    get_variable(model, 'a.inlet.x').set_value(None)
    result = initialize_model(model, solver=solver)
    assert result.failed_model == 'a'
    assert result.stages[0].status == 'underconstrained'
    assert get_variable(model, 'a.inlet.x').name in result.stages[0].missing_starting_values
    assert all(not v.fixed for v in model.component_data_objects(Var))


def test_solver_failure_restores_stage_values_and_flags(tmp_path):
    model = build_plant(tmp_path)
    before = [(v, v.value, v.fixed) for v in model.component_data_objects(Var)]
    class FailingSolver:
        def solve(self, block, **kwargs):
            block.structs.outlet.y.set_value(999)
            block.relationship.constraints.balance.deactivate()
            raise RuntimeError('deliberate failure')
    result = initialize_model(model, solver=FailingSolver())
    assert result.stages[0].status == 'error'
    assert 'deliberate failure' in result.stages[0].error
    assert all(v.value == old and v.fixed == fixed for v, old, fixed in before)
    assert model.fs.root.relationship.models.a.relationship.constraints.balance.active


def test_nonoptimal_termination_is_failure_and_rolls_back(tmp_path):
    model = build_plant(tmp_path)
    class FailedSolver:
        def solve(self, block, **kwargs):
            block.structs.outlet.y.set_value(999)
            return SimpleNamespace(solver=SimpleNamespace(
                status=SolverStatus.warning, termination_condition=TerminationCondition.maxIterations))
    result = initialize_model(model, solver=FailedSolver())
    assert result.stages[0].status == 'solver_failed'
    assert result.stages[0].solver_termination == 'maxIterations'
    assert get_variable(model, 'a.outlet.y').value is None
    assert not get_variable(model, 'a.inlet.x').fixed


def test_successful_status_without_feasible_values_is_rejected(tmp_path):
    model = build_plant(tmp_path)
    class LyingSolver:
        def solve(self, block, **kwargs):
            block.structs.outlet.y.set_value(999)
            return SimpleNamespace(solver=SimpleNamespace(
                status=SolverStatus.ok, termination_condition=TerminationCondition.optimal))
    result = initialize_model(model, solver=LyingSolver())
    assert result.stages[0].status == 'residual_failed'
    assert get_variable(model, 'a.outlet.y').value is None


def test_hierarchy_metadata_follows_cloning(tmp_path, solver):
    original = build_plant(tmp_path)
    model = original.clone()
    get_variable(model, 'inlet.x').fix(4)
    assert initialize_model(model, solver=solver).success
    assert get_variable(model, 'outlet.y').value == pytest.approx(16)
    assert get_variable(original, 'outlet.y').value is None
    assert not get_variable(original, 'inlet.x').fixed


def test_dm_recomputed_after_each_fix_and_information_rank_is_used(tmp_path, solver):
    library = Library(tmp_path)
    library.models['sum'] = ModelDocument.model_validate({
        'id': 'sum', 'structs': {
            'inlet': {'direction': 'input', 'variables': {
                'x': {'default': 1}, 'y': {'default': 1}, 'z': {'default': 1}}},
            'outlet': {'direction': 'output', 'variables': {'total': {}}},
        }, 'relationships': {'sum': {'constraints': {
            'sum': {'lhs': 'outlet.total', 'rhs': 'inlet.x + inlet.y + inlet.z',
                    'determines': 'outlet.total'}}}},
    })
    library.models['plant'] = ModelDocument.model_validate({
        'id': 'plant', 'structs': {'feed': {'direction': 'input', 'variables': {
            'x': {'default': 7}, 'y': {'default': 1}}}},
        'relationships': {'sum': {'models': {'child': {'model': 'sum'}}, 'constraints': {
            'x': {'lhs': 'child.inlet.x', 'rhs': 'feed.x', 'determines': 'child.inlet.x'},
            'y': {'lhs': 'child.inlet.y', 'rhs': 'feed.y', 'determines': 'child.inlet.y'},
        }}},
    })
    model = build_model('plant', {'relationship': 'sum', 'submodels': {
        'child': {'relationship': 'sum'}}}, library=library)
    get_variable(model, 'feed.x').fix(7)
    get_variable(model, 'feed.y').fix(1)
    get_variable(model, 'child.outlet.total').fix(10)
    info = InformationDocument([dict(
        id='z_guess', tag='guess', variable_path='child.inlet.z', value=8,
        unit='dimensionless', information_type='assumption', trust_rank=8)])
    result = initialize_model(model, solver=solver, information=info)
    assert result.success
    stage = result.stages[0]
    assert stage.initial_deficiency == 2
    assert len(stage.temporary_fixes) == 2
    assert stage.temporary_fixes[0]['variable_path'] == 'child.inlet.z'
    assert stage.temporary_fixes[0]['trust_rank'] == 8
    assert stage.temporary_fixes[0]['value'] == 8
    assert [(f['deficiency_before'], f['deficiency_after'])
            for f in stage.temporary_fixes] == [(2, 1), (1, 0)]
    assert get_variable(model, 'child.inlet.z').value == pytest.approx(2)
    assert not get_variable(model, 'child.inlet.z').fixed


def test_overconstraint_is_reported_without_adding_fixes(tmp_path, solver):
    model = build_plant(tmp_path)
    get_variable(model, 'a.inlet.x').fix(1)
    get_variable(model, 'a.outlet.y').fix(9)
    result = initialize_model(model, solver=solver)
    assert result.stages[0].status == 'overconstrained'
    assert result.stages[0].overconstrained_constraints
    assert result.stages[0].temporary_fixes == []
    assert get_variable(model, 'a.outlet.y').value == 9
    assert get_variable(model, 'a.outlet.y').fixed


def test_custom_hooks_run_once_per_occurrence_before_parent_solve(tmp_path, solver):
    library = tiny_library(tmp_path)
    library.models['leaf'].relationships['linear'].constraints = {}
    from multifidelity.model_language.definitions import ExternalRelationship
    library.models['leaf'].relationships['linear'].external = ExternalRelationship(
        provider='linear', dependencies={'outlet.y': ['inlet.x']})
    calls = []
    def provider(block, config):
        block.x = Var()
        block.y = Var()
        block.eq = Constraint(expr=block.y == 2 * block.x)
        return {'inlet.x': block.x, 'outlet.y': block.y}
    def callback(block, config):
        calls.append(block.name)
        assert block.x.fixed
        block.y.set_value(2 * block.x.value)
    library.register_provider('linear', provider, initializer=callback)
    model = build_model('plant', {'relationship': 'flowsheet', 'submodels': {
        'a': {'relationship': 'linear'}, 'b': {'relationship': 'linear'}}}, library=library)
    get_variable(model, 'inlet.x').fix(4)
    result = initialize_model(model, solver=solver)
    assert result.success and len(calls) == 2
    assert get_variable(model, 'outlet.y').value == pytest.approx(16)
    assert [len(s.callbacks) for s in result.stages] == [1, 1, 0]
    assert all(not v.fixed for v in model.component_data_objects(Var)
               if v is not get_variable(model, 'inlet.x'))


def test_dynamic_initialisation_is_explicitly_out_of_scope():
    model = build_model('valve', {'relationship': 'isenthalpic'}, mode='dynamic',
                        domain_values={'time': [0, 1]})
    with pytest.raises(ValueError, match='steady models only'):
        initialize_model(model)


def test_failed_parent_retains_successful_child_values(tmp_path, solver):
    model = build_plant(tmp_path)
    get_variable(model, 'inlet.x').fix(3)
    class FailAtRoot:
        def solve(self, block, **kwargs):
            if block is model.fs.root:
                get_variable(model, 'a.outlet.y').set_value(999)
                raise RuntimeError('parent failed')
            return solver.solve(block, **kwargs)
    result = initialize_model(model, solver=FailAtRoot())
    assert result.failed_model == 'plant'
    assert [s.status for s in result.stages] == ['initialized', 'initialized', 'error']
    assert get_variable(model, 'a.outlet.y').value == pytest.approx(2)
    assert get_variable(model, 'b.outlet.y').value == pytest.approx(2)
    assert get_variable(model, 'inlet.x').fixed
    assert not get_variable(model, 'a.inlet.x').fixed


def test_steady_indexed_inputs_are_closed_entry_by_entry(tmp_path, solver):
    library = tiny_library(tmp_path)
    for model in library.models.values():
        document = model.model_dump()
        document['domains'] = {'time': {'kind': 'time'}}
        for struct in document['structs'].values():
            for variable in struct['variables'].values():
                variable['dimensions'] = ['time']
        for relationship in document['relationships'].values():
            for reference in relationship['models'].values():
                reference['domain_bindings'] = {'time': 'time'}
            for equation in relationship['constraints'].values():
                equation['for_each'] = {'t': 'time'}
                for side in ['lhs', 'rhs', 'determines']:
                    equation[side] = equation[side].replace('inlet.x', 'inlet.x[t]').replace('outlet.y', 'outlet.y[t]')
        library.models[model.id] = ModelDocument.model_validate(document)
    model = build_model('plant', {'relationship': 'flowsheet', 'submodels': {
        'a': {'relationship': 'linear'}, 'b': {'relationship': 'linear'}}},
        library=library, domain_values={'time': [0, 10]})
    get_variable(model, 'inlet.x')[0].fix(3)
    get_variable(model, 'inlet.x')[10].fix(4)
    result = initialize_model(model, solver=solver)
    assert result.success
    assert [len(s.temporary_fixes) for s in result.stages] == [2, 2, 0]
    assert get_variable(model, 'outlet.y')[0].value == pytest.approx(12)
    assert get_variable(model, 'outlet.y')[10].value == pytest.approx(16)


def test_hidden_internal_freedom_is_reported_instead_of_arbitrarily_fixed(tmp_path):
    library = tiny_library(tmp_path)
    from multifidelity.model_language.definitions import ExternalRelationship
    relationship = library.models['leaf'].relationships['linear']
    relationship.constraints = {}
    relationship.external = ExternalRelationship(
        provider='orphan', dependencies={'outlet.y': ['inlet.x']})
    def provider(block, config):
        block.x = Var()
        block.y = Var()
        block.orphan = Var(initialize=3)
        block.eq = Constraint(expr=block.y == 2 * block.x)
        return {'inlet.x': block.x, 'outlet.y': block.y}
    library.register_provider('orphan', provider)
    model = build_model('plant', {'relationship': 'flowsheet', 'submodels': {
        'a': {'relationship': 'linear'}, 'b': {'relationship': 'linear'}}}, library=library)
    result = initialize_model(model)
    assert result.failed_model == 'a'
    stage = result.stages[0]
    assert stage.status == 'underconstrained'
    assert stage.initial_deficiency == 2 and stage.remaining_deficiency == 1
    assert any('orphan' in name for name in stage.unresolved_variables)
    assert all(not v.fixed for v in model.component_data_objects(Var))
