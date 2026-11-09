import json

import pytest
from pydantic import ValidationError

from multifidelity.model_language import (
    InformationDocument, WorkspaceDocument, build_model, export_results,
    export_workspace, get_variable,
)


def information():
    return InformationDocument([{
        'id': 'pressure', 'tag': 'PT1', 'information_type': 'sensor_reading',
        'variable_path': 'inlet.pressure', 'value': 200, 'unit': 'kPa', 'trust_rank': 10,
    }])


def test_model_workspace_roundtrip_has_only_requested_contents(tmp_path):
    model = build_model('valve', {'relationship': 'isenthalpic'})
    get_variable(model, 'inlet.pressure')[0].fix(200000)
    records = information()
    workspace = export_workspace(model, records, status='failed', solver='ipopt',
                                 message='Not converged', specification={'specifications': ['pressure']})
    assert set(workspace.model_dump()) == {'implementation', 'information', 'results'}
    assert workspace.results.model_id == 'valve'
    assert workspace.results.solve.status == 'failed'
    assert workspace.results.specification.specifications == ('pressure',)
    assert workspace.results.implementation == workspace.implementation
    assert workspace.information.records == records.records
    path = tmp_path / 'workspace.json'
    workspace.write_json(path)
    assert WorkspaceDocument.load_json(path) == workspace
    assert isinstance(json.loads(path.read_text())['information'], list)
    records.add({**records.records[0].model_dump(), 'id': 'other'})
    get_variable(model, 'inlet.pressure')[0].set_value(100000)
    assert len(workspace.information.records) == 1
    pressure = next(v for v in workspace.results.variables if v.variable_path == 'inlet.pressure')
    assert pressure.entries[0].value == 200000


def test_bundle_existing_snapshot_preserves_identity_and_reads_files(tmp_path):
    snapshot = export_results(build_model('valve', {'relationship': 'isenthalpic'}))
    results_path = tmp_path / 'results.json'
    snapshot.write_json(results_path)
    information_path = tmp_path / 'information.json'
    information_path.write_text(information().model_dump_json())
    bundle = WorkspaceDocument.from_results(results_path, information_path)
    assert bundle.results == snapshot
    assert bundle.results.run_id == snapshot.run_id
    assert bundle.results.created_at == snapshot.created_at
    assert bundle.results.solve.status == 'not_solved'


def test_incompatible_and_extra_workspace_fields_are_rejected():
    workspace = export_workspace(build_model('valve', {'relationship': 'isenthalpic'}), information())
    document = json.loads(workspace.model_dump_json())
    for change in [lambda d: d.update(model_id='valve'), lambda d: d.update(layouts={}),
                   lambda d: d['implementation'].update(relationship='other'),
                   lambda d: d.update(information=[{}, {}]), lambda d: d.update(results=None)]:
        invalid = json.loads(json.dumps(document))
        change(invalid)
        with pytest.raises(ValidationError):
            WorkspaceDocument.model_validate(invalid)
