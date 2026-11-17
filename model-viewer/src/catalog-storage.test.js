import { test } from 'node:test';
import assert from 'node:assert/strict';
import { catalogKey, loadCatalogs, persistCatalogs, loadActiveBlock, saveActiveBlock } from './catalog-storage.js';
function storage() {
  const entries = new Map();
  return { get length() { return entries.size; }, key: index => [...entries.keys()][index], getItem: key => entries.get(key) ?? null, setItem: (key, value) => entries.set(key, value), removeItem: key => entries.delete(key) };
}
const model_catalog = { formulation: 'isenthalpic', subblocks: {} };
const resources = { name: 'resources.json', records: [{ tag: 'p', resource_type: 'sensor_reading', variable_path: 'inlet.pressure', type: 'constant', value: 200, unit: 'kPa', trust_rank: 8 }] };
const results = { name: 'results.json', catalog: { schema_version: 1, run_id: 'r', created_at: '2026-11-05T00:00:00Z', block_id: 'valve', model_catalog, mode: 'steady', time_unit: 's', solve: { status: 'optimal' }, variables: [] } };

test('model_catalog, resources and results survive refresh independently by root', () => {
  const local = storage();
  for (const [kind, value] of [['model_catalog', model_catalog], ['resources', resources], ['results', results]]) {
    assert.deepEqual(persistCatalogs(kind, { valve: value }, {}, local).errors, []);
    assert.deepEqual(loadCatalogs(kind, local), { catalogs: { valve: value }, errors: [] });
  }
  const changed = { ...resources, records: [...resources.records, { ...resources.records[0], tag: 'alternative', value: 210 }] };
  persistCatalogs('resources', { valve: changed, pump: resources }, { valve: resources }, local);
  assert.equal(loadCatalogs('resources', local).catalogs.valve.records.length, 2);
  assert.equal(loadCatalogs('resources', local).catalogs.pump.records.length, 1);
  assert.deepEqual(loadCatalogs('model_catalog', local).catalogs.valve, model_catalog);
  assert.deepEqual(loadCatalogs('results', local).catalogs.valve, results);
});

test('clear removes the saved copy and other keys are untouched', () => {
  const local = storage();
  local.setItem('multifidelity:layout:v1:other', '{}');
  const previous = persistCatalogs('resources', { valve: resources }, {}, local).saved;
  persistCatalogs('resources', { valve: null }, previous, local);
  assert.deepEqual(loadCatalogs('resources', local).catalogs, {});
  assert.equal(local.getItem('multifidelity:layout:v1:other'), '{}');
});

test('malformed catalogs are skipped without losing valid catalogs', () => {
  const local = storage();
  local.setItem(catalogKey('resources', 'bad'), '{bad');
  local.setItem(catalogKey('resources', 'invalid'), '{"name":"x", "records":{}}');
  persistCatalogs('resources', { valve: resources }, {}, local);
  const loaded = loadCatalogs('resources', local);
  assert.deepEqual(loaded.catalogs, { valve: resources });
  assert.equal(loaded.errors.length, 2);
  local.setItem(catalogKey('results', 'pump'), JSON.stringify(results));
  assert.equal(loadCatalogs('results', local).errors.length, 1);
});

test('incomplete model_catalog drafts can be restored and corrected in editor', () => {
  const local = storage();
  const draft = { formulation: 'r', subblocks: { child: { formulation: '', subblocks: {} } } };
  persistCatalogs('model_catalog', { draft }, {}, local);
  assert.deepEqual(loadCatalogs('model_catalog', local).catalogs.draft, draft);
});

test('full or disabled storage reports failure and retains in-memory catalogs', () => {
  const unavailable = { get length() { throw Error('denied'); }, setItem() { throw Error('quota'); }, removeItem() { throw Error('denied'); } };
  assert.equal(loadCatalogs('resources', unavailable).errors.length, 1);
  const catalogs = { valve: resources };
  const result = persistCatalogs('resources', catalogs, {}, unavailable);
  assert.equal(result.errors.length, 1);
  assert.deepEqual(result.saved, {});
  assert.equal(catalogs.valve, resources);
});


test('refresh reopens the last root and falls back if it is no longer in the library', () => {
  const local = storage();
  saveActiveBlock('valve', local);
  assert.equal(loadActiveBlock({ valve: {} }, 'default', local), 'valve');
  assert.equal(loadActiveBlock({}, 'default', local), 'default');
});
