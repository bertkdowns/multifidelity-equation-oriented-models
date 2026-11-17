import json

import pytest
from pydantic import ValidationError

from multifidelity.model_language import (
    ResourceDocument, WorkspaceDocument, build_model, export_results,
    export_workspace, get_variable,
)


def resources():
    return ResourceDocument([{
        'tag': 'pressure', 'resource_type': 'sensor_reading',
        'variable_path': 'inlet.pressure', 'value': 200, 'unit': 'kPa', 'trust_rank': 10,
    }])


def test_model_workspace_roundtrip_has_only_requested_contents(tmp_path):
    model = build_model('valve', {'formulation': 'isenthalpic'})
    get_variable(model, 'inlet.pressure')[0].fix(200000)
    records = resources()
    workspace = export_workspace(model, records, status='failed', solver='ipopt',
                                 message='Not converged', parameters={'parameters': ['pressure']})
    assert set(workspace.model_dump()) == {'model_document', 'resources', 'results'}
    assert workspace.results.block_id == 'valve'
    assert workspace.results.solve.status == 'failed'
    assert workspace.results.parameters.parameters == ('pressure',)
    assert workspace.results.model_document == workspace.model_document
    assert workspace.resources.records == records.records
    path = tmp_path / 'workspace.json'
    workspace.write_json(path)
    assert WorkspaceDocument.load_json(path) == workspace
    assert isinstance(json.loads(path.read_text())['resources'], list)
    records.add({**records.records[0].model_dump(), 'tag': 'other'})
    get_variable(model, 'inlet.pressure')[0].set_value(100000)
    assert len(workspace.resources.records) == 1
    pressure = next(v for v in workspace.results.variables if v.variable_path == 'inlet.pressure')
    assert pressure.entries[0].value == 200000


def test_bundle_existing_snapshot_preserves_identity_and_reads_files(tmp_path):
    snapshot = export_results(build_model('valve', {'formulation': 'isenthalpic'}))
    results_path = tmp_path / 'results.json'
    snapshot.write_json(results_path)
    resources_path = tmp_path / 'resources.json'
    resources_path.write_text(resources().model_dump_json())
    bundle = WorkspaceDocument.from_results(results_path, resources_path)
    assert bundle.results == snapshot
    assert bundle.results.run_id == snapshot.run_id
    assert bundle.results.created_at == snapshot.created_at
    assert bundle.results.solve.status == 'not_solved'


def test_incompatible_and_extra_workspace_fields_are_rejected():
    workspace = export_workspace(build_model('valve', {'formulation': 'isenthalpic'}), resources())
    catalog = json.loads(workspace.model_dump_json())
    for change in [lambda d: d.update(block_id='valve'), lambda d: d.update(layouts={}),
                   lambda d: d['model_document'].update(formulation='other'),
                   lambda d: d.update(resources=[{}, {}]), lambda d: d.update(results=None)]:
        invalid = json.loads(json.dumps(catalog))
        change(invalid)
        with pytest.raises(ValidationError):
            WorkspaceDocument.model_validate(invalid)
