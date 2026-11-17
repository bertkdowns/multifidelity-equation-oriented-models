import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { parseResources, indexResources, resourcePreview, findVariable, appendResource } from './resources.js';
const fixture = { tag: 'r', resource_type: 'sensor_reading', variable_path: 'inlet.pressure', value: 200, unit: 'kPa', trust_rank: 8 };
const directory = new URL('../../src/multifidelity/model_language/blocks/', import.meta.url);
const registry = Object.fromEntries(readdirSync(directory).filter(name => name.endsWith('.json')).map(name => {
  const model = JSON.parse(readFileSync(new URL(name, directory), 'utf8')); return [model.id, model];
}));

test('real example files load and alternatives retain their original values and units', () => {
  for (const path of ['parameters/resources.json', 'dynamic_tank/resources.json', 'resources/records.json', 'steam_generating_heat_pump_system/resources.json']) {
    const records = parseResources(readFileSync(new URL(`../../examples/${path}`, import.meta.url), 'utf8'));
    assert.ok(records.length);
  }
  const records = parseResources(JSON.stringify([fixture, { ...fixture, tag: 'fallback', trust_rank: 1 }, { ...fixture, tag: 'a' }]));
  const index = indexResources(records);
  assert.deepEqual(index.get('inlet.pressure').map(record => record.tag), ['a', 'r', 'fallback']);
  assert.equal(index.get('inlet.pressure')[0].unit, 'kPa');
  assert.equal(resourcePreview(index.get('inlet.pressure')[0]), '200');
});

test('invalid records are rejected atomically', () => {
  for (const value of [{}, [fixture, fixture], [{ ...fixture, trust_rank: true }], [{ ...fixture, unit: '' }], [{ ...fixture, value: [1] }], [{ ...fixture, type: 'series', value: 1 }], [{ ...fixture, type: 'series', value: [[1], [2, 3]] }], [{ ...fixture, value: true }], [{ ...fixture, standard_deviation: -1 }], [{ ...fixture, extra: 'unknown' }], [{ ...fixture, id: 'unsupported_id' }]])
    assert.throws(() => parseResources(JSON.stringify(value)));
  assert.throws(() => parseResources('{broken'));
});

test('series previews show shape without inventing time coordinates', () => {
  assert.equal(resourcePreview({ type: 'series', value: [1, 2, 3] }), 'Series · 3 samples');
  assert.equal(resourcePreview({ type: 'series', value: [[1, 2], [3, 4]] }), 'Array · 2 × 2');
});

test('paths match the root and nested occurrences independently, across formulations', () => {
  const context = { definition: registry.steam_generating_heat_pump_unit, bindings: {} };
  assert.equal(findVariable(context, 'condenser.parameters.conductance', registry).unit, 'W/K');
  assert.equal(findVariable(context, 'cop_model.parameters.cop', registry).unit, 'dimensionless');
  assert.equal(findVariable(context, 'wrong.parameters.conductance', registry), undefined);
  const index = indexResources([{ ...fixture, variable_path: 'a.inlet.pressure' }, { ...fixture, tag: 'other', variable_path: 'b.inlet.pressure', value: 300 }]);
  assert.equal(index.get('a.inlet.pressure')[0].value, 200);
  assert.equal(index.get('b.inlet.pressure')[0].value, 300);
  const tank = { definition: registry.tank, bindings: {} };
  assert.deepEqual(findVariable(tank, 'inventory.level', registry).dimensions, ['time']);
});

const draft = { tag: 'new', variable_path: 'inlet.pressure', resource_type: 'sensor_reading', type: 'constant', value: '220.5', unit: 'kPa', trust_rank: '10', standard_deviation: '' };

test('adding a record preserves alternatives and updates the diagram preview ordering', () => {
  const previous = [fixture];
  const records = appendResource(previous, draft);
  assert.equal(previous.length, 1);
  assert.equal(records.length, 2);
  assert.equal(records[1].value, 220.5);
  assert.equal(records[1].trust_rank, 10);
  assert.equal(records[1].unit, 'kPa');
  assert.ok(!('standard_deviation' in records[1]));
  assert.equal(indexResources(records).get('inlet.pressure')[0].tag, 'new');
  assert.deepEqual(parseResources(JSON.stringify(records)), records);
});

test('record form accepts multidimensional series, zero and unknown paths', () => {
  const records = appendResource([], { ...draft, type: 'series', value: '[[1,2],[3,4]]', variable_path: 'future.model.value', standard_deviation: '0' });
  assert.deepEqual(records[0].value, [[1,2],[3,4]]);
  assert.equal(records[0].standard_deviation, 0);
  assert.equal(records[0].variable_path, 'future.model.value');
  assert.equal(appendResource([], { ...draft, value: '0' })[0].value, 0);
});

test('record form rejects duplicates and bad numbers without changing existing records', () => {
  const previous = [fixture];
  for (const change of [{ tag: 'r' }, { tag: ' ' }, { value: '' }, { value: 'NaN' }, { value: 'true' }, { value: '1e999' }, { trust_rank: '11' }, { unit: '' }, { standard_deviation: 'Infinity' }, { standard_deviation: 'no' }, { standard_deviation: '-1' }, { type: 'series', value: '[[1], [2,3]]' }]) {
    assert.throws(() => appendResource(previous, { ...draft, ...change }));
    assert.equal(previous.length, 1);
    assert.equal(previous[0].value, 200);
  }
});
