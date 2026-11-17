import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseFeeds, updateFeed } from './feeds.js';
import { parseWorkspace } from './workspace.js';
import { catalogKey, loadCatalogs, persistCatalogs } from './catalog-storage.js';
const fixture = () => [{ name: 'plant', provider_type: 'example.PlantFeed', tags: ['flow'], config: { columns: { flow: 'FT101' }, enabled: true } }];

test('catalogue roundtrips configuration without interpreting connector code', () => {
  const source = fixture();
  assert.deepEqual(parseFeeds(JSON.stringify(source)), source);
  const changed = updateFeed(source, 'plant', { dataset: 'new' });
  assert.deepEqual(changed[0].tags, ['flow']);
  assert.deepEqual(changed[0].config, { dataset: 'new' });
  assert.deepEqual(source, fixture());
});

test('invalid declarations and conflicting assignments fail atomically', () => {
  for (const value of [{}, [null], [{ ...fixture()[0], config: [] }], [{ ...fixture()[0], name: ' ' }], [{ ...fixture()[0], tags: 'flow' }], [{ ...fixture()[0], tags: ['flow', 'flow'] }], [{ ...fixture()[0], extra: 'code' }], [...fixture(), { ...fixture()[0], name: 'other' }], [...fixture(), { ...fixture()[0], tags: ['pressure'] }]])
    assert.throws(() => parseFeeds(JSON.stringify(value)));
  assert.throws(() => parseFeeds('[{"name":"p","provider_type":"P","tags":[],"config":{"value":1e999}}]'));
  const source = [...fixture(), { ...fixture()[0], name: 'other', tags: ['pressure'] }];
  assert.deepEqual(updateFeed(source, 'plant', {}).map(p => p.tags), [['flow'], ['pressure']]);
  assert.deepEqual(source[0].tags, ['flow']);
  assert.throws(() => updateFeed(source, 'missing', {}));
  assert.throws(() => updateFeed(source, 'plant', { value: Infinity }));
});

test('feed catalogue survives browser storage and workspace export/import', () => {
  const entries = new Map();
  const local = { get length() { return entries.size; }, key: i => [...entries.keys()][i], getItem: key => entries.get(key), setItem: (key, value) => entries.set(key, value), removeItem: key => entries.delete(key) };
  const file = { name: 'feeds.json', feeds: fixture() };
  persistCatalogs('feeds', { valve: file }, {}, local);
  assert.deepEqual(loadCatalogs('feeds', local), { catalogs: { valve: file }, errors: [] });
  local.setItem(catalogKey('feeds', 'invalid'), '{"name":"bad","feeds":{}}');
  assert.equal(loadCatalogs('feeds', local).errors.length, 1);
  const results = { schema_version: 1, run_id: 'r', created_at: '2026-11-16T00:00:00Z', block_id: 'valve', model_catalog: { formulation: 'r' }, mode: 'steady', time_unit: 's', solve: { status: 'not_solved' }, variables: [] };
  const workspace = { model_catalog: results.model_catalog, resources: [], results, feeds: fixture() };
  assert.deepEqual(parseWorkspace(JSON.stringify(workspace)).feeds, fixture());
  assert.throws(() => parseWorkspace(JSON.stringify({ ...workspace, feeds: {} })));
  delete workspace.feeds;
  assert.ok(!('feeds' in parseWorkspace(JSON.stringify(workspace))));
});
