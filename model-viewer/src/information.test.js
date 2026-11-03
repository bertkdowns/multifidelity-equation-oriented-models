import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { parseInformation, indexInformation, informationPreview, findVariable } from './information.js';
const fixture = { id: 'r', tag: 'T', information_type: 'sensor_reading', variable_path: 'inlet.pressure', value: 200, unit: 'kPa', trust_rank: 8 };
const directory = new URL('../../src/multifidelity/model_language/models/', import.meta.url);
const library = Object.fromEntries(readdirSync(directory).filter(name => name.endsWith('.json')).map(name => {
  const model = JSON.parse(readFileSync(new URL(name, directory), 'utf8')); return [model.id, model];
}));

test('real example files load and alternatives retain their original values and units', () => {
  for (const path of ['specification/information.json', 'dynamic_tank/information.json', 'information/records.json', 'steam_generating_heat_pump_system/information.json']) {
    const records = parseInformation(readFileSync(new URL(`../../examples/${path}`, import.meta.url), 'utf8'));
    assert.ok(records.length);
  }
  const records = parseInformation(JSON.stringify([fixture, { ...fixture, id: 'fallback', trust_rank: 1 }, { ...fixture, id: 'a' }]));
  const index = indexInformation(records);
  assert.deepEqual(index.get('inlet.pressure').map(record => record.id), ['a', 'r', 'fallback']);
  assert.equal(index.get('inlet.pressure')[0].unit, 'kPa');
  assert.equal(informationPreview(index.get('inlet.pressure')[0]), '200');
});

test('invalid records are rejected atomically', () => {
  for (const value of [{}, [fixture, fixture], [{ ...fixture, trust_rank: true }], [{ ...fixture, unit: '' }], [{ ...fixture, value: [1] }], [{ ...fixture, type: 'series', value: 1 }], [{ ...fixture, type: 'series', value: [[1], [2, 3]] }], [{ ...fixture, value: true }], [{ ...fixture, standard_deviation: -1 }], [{ ...fixture, extra: 'unknown' }]])
    assert.throws(() => parseInformation(JSON.stringify(value)));
  assert.throws(() => parseInformation('{broken'));
});

test('series previews show shape without inventing time coordinates', () => {
  assert.equal(informationPreview({ type: 'series', value: [1, 2, 3] }), 'Series · 3 samples');
  assert.equal(informationPreview({ type: 'series', value: [[1, 2], [3, 4]] }), 'Array · 2 × 2');
});

test('paths match the root and nested occurrences independently, across relationships', () => {
  const context = { definition: library.steam_generating_heat_pump_unit, bindings: {} };
  assert.equal(findVariable(context, 'condenser.parameters.conductance', library).unit, 'W/K');
  assert.equal(findVariable(context, 'cop_model.parameters.cop', library).unit, 'dimensionless');
  assert.equal(findVariable(context, 'wrong.parameters.conductance', library), undefined);
  const index = indexInformation([{ ...fixture, variable_path: 'a.inlet.pressure' }, { ...fixture, id: 'other', variable_path: 'b.inlet.pressure', value: 300 }]);
  assert.equal(index.get('a.inlet.pressure')[0].value, 200);
  assert.equal(index.get('b.inlet.pressure')[0].value, 300);
  const tank = { definition: library.tank, bindings: {} };
  assert.deepEqual(findVariable(tank, 'inventory.level', library).dimensions, ['time']);
});
