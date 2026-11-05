import { test } from 'node:test';
import assert from 'node:assert/strict';
import { documentKey, loadDocuments, persistDocuments, loadActiveModel, saveActiveModel } from './document-storage.js';
function storage() {
  const entries = new Map();
  return { get length() { return entries.size; }, key: index => [...entries.keys()][index], getItem: key => entries.get(key) ?? null, setItem: (key, value) => entries.set(key, value), removeItem: key => entries.delete(key) };
}
const implementation = { relationship: 'isenthalpic', submodels: {} };
const information = { name: 'information.json', records: [{ id: 'p', tag: 'P', information_type: 'sensor_reading', variable_path: 'inlet.pressure', type: 'constant', value: 200, unit: 'kPa', trust_rank: 8 }] };
const results = { name: 'results.json', document: { schema_version: 1, run_id: 'r', created_at: '2026-11-05T00:00:00Z', model_id: 'valve', implementation, mode: 'steady', time_unit: 's', solve: { status: 'optimal' }, variables: [] } };

test('implementation, information and results survive refresh independently by root', () => {
  const local = storage();
  for (const [kind, value] of [['implementation', implementation], ['information', information], ['results', results]]) {
    assert.deepEqual(persistDocuments(kind, { valve: value }, {}, local).errors, []);
    assert.deepEqual(loadDocuments(kind, local), { documents: { valve: value }, errors: [] });
  }
  const changed = { ...information, records: [...information.records, { ...information.records[0], id: 'alternative', value: 210 }] };
  persistDocuments('information', { valve: changed, pump: information }, { valve: information }, local);
  assert.equal(loadDocuments('information', local).documents.valve.records.length, 2);
  assert.equal(loadDocuments('information', local).documents.pump.records.length, 1);
  assert.deepEqual(loadDocuments('implementation', local).documents.valve, implementation);
  assert.deepEqual(loadDocuments('results', local).documents.valve, results);
});

test('clear removes the saved copy and other keys are untouched', () => {
  const local = storage();
  local.setItem('multifidelity:layout:v1:other', '{}');
  const previous = persistDocuments('information', { valve: information }, {}, local).saved;
  persistDocuments('information', { valve: null }, previous, local);
  assert.deepEqual(loadDocuments('information', local).documents, {});
  assert.equal(local.getItem('multifidelity:layout:v1:other'), '{}');
});

test('malformed documents are skipped without losing valid documents', () => {
  const local = storage();
  local.setItem(documentKey('information', 'bad'), '{bad');
  local.setItem(documentKey('information', 'invalid'), '{"name":"x", "records":{}}');
  persistDocuments('information', { valve: information }, {}, local);
  const loaded = loadDocuments('information', local);
  assert.deepEqual(loaded.documents, { valve: information });
  assert.equal(loaded.errors.length, 2);
  local.setItem(documentKey('results', 'pump'), JSON.stringify(results));
  assert.equal(loadDocuments('results', local).errors.length, 1);
});

test('incomplete implementation drafts can be restored and corrected in editor', () => {
  const local = storage();
  const draft = { relationship: 'r', submodels: { child: { relationship: '', submodels: {} } } };
  persistDocuments('implementation', { draft }, {}, local);
  assert.deepEqual(loadDocuments('implementation', local).documents.draft, draft);
});

test('full or disabled storage reports failure and retains in-memory documents', () => {
  const unavailable = { get length() { throw Error('denied'); }, setItem() { throw Error('quota'); }, removeItem() { throw Error('denied'); } };
  assert.equal(loadDocuments('information', unavailable).errors.length, 1);
  const documents = { valve: information };
  const result = persistDocuments('information', documents, {}, unavailable);
  assert.equal(result.errors.length, 1);
  assert.deepEqual(result.saved, {});
  assert.equal(documents.valve, information);
});


test('refresh reopens the last root and falls back if it is no longer in the library', () => {
  const local = storage();
  saveActiveModel('valve', local);
  assert.equal(loadActiveModel({ valve: {} }, 'default', local), 'valve');
  assert.equal(loadActiveModel({}, 'default', local), 'default');
});
