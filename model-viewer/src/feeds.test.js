import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseFeeds, updateFeed } from './feeds.js';
import { parseWorkspace } from './workspace.js';
import { catalogKey, loadCatalogs, persistCatalogs } from './catalog-storage.js';
const fixture = () => ({ feeds: [{ name: 'plant', provider_type: 'plant', config: { columns: { flow: 'FT101' }, enabled: true } }] });

test('document roundtrips plugin settings without executing code', () => {
  const source = fixture();
  assert.deepEqual(parseFeeds(JSON.stringify(source)), source);
  const changed = updateFeed(source, 'plant', { dataset: 'new' });
  assert.deepEqual(changed.feeds[0].config, { dataset: 'new' });
  assert.equal(changed.feeds[0].provider_type, 'plant');
  assert.deepEqual(source, fixture());
});

test('invalid documents and duplicate instance names are rejected', () => {
  const entry = fixture().feeds[0];
  for (const value of [[], {}, { feeds: [null] }, { feeds: [{ ...entry, config: [] }] },
    { feeds: [{ ...entry, name: ' ' }] }, { feeds: [{ ...entry, tags: [] }] },
    { feeds: [entry, entry] }, { feeds: [], extra: true }])
    assert.throws(() => parseFeeds(JSON.stringify(value)));
  assert.throws(() => updateFeed(fixture(), 'missing', {}));
  assert.throws(() => updateFeed(fixture(), 'plant', { value: Infinity }));
  assert.doesNotThrow(() => parseFeeds(JSON.stringify({ feeds: [entry, { ...entry, name: 'other' }] })));
});

test('feed document survives browser storage and workspace export/import', () => {
  const entries = new Map();
  const local = { get length() { return entries.size; }, key: i => [...entries.keys()][i], getItem: key => entries.get(key), setItem: (key, value) => entries.set(key, value), removeItem: key => entries.delete(key) };
  const file = { name: 'feeds.json', feeds: fixture() };
  persistCatalogs('feeds', { valve: file }, {}, local);
  assert.deepEqual(loadCatalogs('feeds', local), { catalogs: { valve: file }, errors: [] });
  local.setItem(catalogKey('feeds', 'invalid'), '{"name":"bad","feeds":{}}');
  assert.equal(loadCatalogs('feeds', local).errors.length, 1);
  const results = { schema_version: 1, run_id: 'r', created_at: '2026-11-16T00:00:00Z', block_id: 'valve', model_document: { formulation: 'r' }, mode: 'steady', time_unit: 's', solve: { status: 'not_solved' }, variables: [] };
  const workspace = { model_document: results.model_document, resources: [], results, feeds: fixture() };
  assert.deepEqual(parseWorkspace(JSON.stringify(workspace)).feeds, fixture());
  assert.throws(() => parseWorkspace(JSON.stringify({ ...workspace, feeds: {} })));
  delete workspace.feeds;
  assert.ok(!('feeds' in parseWorkspace(JSON.stringify(workspace))));
});
