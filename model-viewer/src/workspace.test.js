import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseWorkspace } from './workspace.js';
const fixture = () => ({ implementation: { relationship: 'r', submodels: {} }, information: [], results: { schema_version: 1, run_id: 'run', created_at: '2026-11-09T00:00:00Z', model_id: 'valve', implementation: { relationship: 'r' }, mode: 'steady', time_unit: 's', solve: { status: 'failed' }, variables: [] } });

test('workspace round trip contains only choices, records and the original snapshot', () => {
  const source = fixture();
  const workspace = parseWorkspace(JSON.stringify(source));
  assert.deepEqual(Object.keys(workspace).sort(), ['implementation', 'information', 'results']);
  assert.equal(workspace.results.model_id, 'valve');
  assert.equal(workspace.results.solve.status, 'failed');
  assert.equal(workspace.results.run_id, 'run');
  assert.deepEqual(parseWorkspace(JSON.stringify(workspace)), workspace);
});

test('invalid contents, UI state and mismatched implementation are rejected', () => {
  for (const change of [doc => doc.implementation.relationship = 'other', doc => doc.results = null, doc => doc.information = {}, doc => doc.model_id = 'valve', doc => doc.layout = {}, doc => delete doc.implementation]) {
    const doc = fixture(); change(doc);
    assert.throws(() => parseWorkspace(JSON.stringify(doc)));
  }
  assert.throws(() => parseWorkspace('[]'));
  assert.throws(() => parseWorkspace('{broken'));
});

test('Python-generated aggregate and cycle SGHP workspaces load directly', () => {
  for (const filename of ['workspace.json', 'cycle_workspace.json']) {
    const workspace = parseWorkspace(readFileSync(new URL(`../../examples/steam_generating_heat_pump_system/${filename}`, import.meta.url), 'utf8'));
    assert.equal(workspace.results.model_id, 'steam_generating_heat_pump_system');
    assert.ok(workspace.results.variables.length > 100);
    assert.ok(workspace.information.length > 0);
    assert.equal(workspace.implementation.submodels.sghp.relationship, filename === 'workspace.json' ? 'aggregate' : 'cycle');
  }
});
