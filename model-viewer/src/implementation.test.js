import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { defaultImplementation, parseImplementation, analyzeImplementation, selectionAt, replaceSelection } from './implementation.js';
import { resolveReference } from './graph.js';
const dir = new URL('../../src/multifidelity/model_language/models/', import.meta.url);
const library = Object.fromEntries(readdirSync(dir).filter(name => name.endsWith('.json')).map(name => {
  const model = JSON.parse(readFileSync(new URL(name, dir), 'utf8')); return [model.id, model];
}));
const context = id => ({ definition: library[id], bindings: {} });
const example = path => parseImplementation(readFileSync(new URL(`../../examples/${path}`, import.meta.url), 'utf8'));

test('SGHP alternative combinations produce expected heat-pump subtree inputs and portable round trips', () => {
  for (const [name, expected] of [['aggregate_aggregate', 5], ['aggregate_cycle', 10], ['cycle_aggregate', 9], ['cycle_cycle', 14]]) {
    const document = example(`steam_generating_heat_pump_system/${name}.json`);
    const result = analyzeImplementation(context('steam_generating_heat_pump_system'), document, library);
    assert.deepEqual(result.errors, []);
    assert.equal(result.inputs.filter(input => input.path.startsWith('sghp.') || input.path.startsWith('phnix.')).length, expected);
    assert.deepEqual(parseImplementation(JSON.stringify(document)), document);
    assert.ok(!('model' in document));
  }
});

test('changing a child prunes stale descendants, preserves siblings and updates inputs', () => {
  const root = context('steam_generating_heat_pump_system');
  const original = defaultImplementation(root, library);
  const sghp = resolveReference(root.definition.relationships.flowsheet.models.sghp, {}, library);
  const cycle = defaultImplementation(sghp, library, 'cycle');
  const changed = replaceSelection(original, ['sghp'], cycle);
  assert.equal(selectionAt(changed, ['sghp']).relationship, 'cycle');
  assert.equal(selectionAt(original, ['sghp']).relationship, 'aggregate');
  assert.equal(changed.submodels.phnix, original.submodels.phnix);
  assert.ok(!changed.submodels.sghp.submodels.cop_model);
  const result = analyzeImplementation(root, changed, library);
  assert.deepEqual(result.errors, []);
  assert.equal(result.inputs.length - analyzeImplementation(root, original, library).inputs.length, 4);
});

test('input requirements exclude supplied child fields, retaining partial structs and generic children', () => {
  const document = example('model_language/pump_flowsheet.json');
  const result = analyzeImplementation(context('pump_flowsheet'), document, library);
  assert.deepEqual(result.errors, []);
  assert.equal(result.inputs.length, 5);
  assert.ok(result.inputs.some(item => item.path === 'pump.inlet.pressure'));
  assert.ok(!result.inputs.some(item => item.path.includes('outlet_state') && item.name === 'pressure'));
  assert.ok(!result.inputs.some(item => item.path.includes('coefficients')));
});

test('dynamic initial families are reported separately from inputs', () => {
  const document = example('model_language/tank_mixed.json');
  const result = analyzeImplementation(context('tank_flowsheet'), document, library);
  assert.deepEqual(result.errors, []);
  assert.equal(result.inputs.length, 7);
  assert.deepEqual(result.initial.map(item => item.path).sort(), ['tank.inventory.energy', 'tank.inventory.mass']);
});

test('upload rejects malformed shape, wrong relationships and stale child aliases', () => {
  for (const document of [null, [], { model: 'valve', relationship: 'isenthalpic' }, { relationship: '' }, { relationship: 'x', submodels: [] }])
    assert.throws(() => parseImplementation(JSON.stringify(document)));
  assert.throws(() => parseImplementation('{broken'));
  const wrong = analyzeImplementation(context('valve'), { relationship: 'bad' }, library);
  assert.ok(wrong.errors.some(message => message.includes('valid relationship')));
  const stale = analyzeImplementation(context('valve'), { relationship: 'isenthalpic', submodels: { stale: { relationship: 'a' } } }, library);
  assert.ok(stale.errors.some(message => message.includes('submodels must be exactly')));
});

test('recursive defaults stop and allow an explicit terminating relationship', () => {
  const recursive = { id: 'recursive', structs: {}, relationships: { recur: { models: { child: { model: 'recursive' } } }, end: {} } };
  const root = { definition: recursive, bindings: {} };
  const lib = { recursive };
  const defaults = defaultImplementation(root, lib);
  assert.equal(defaults.submodels.child.relationship, '');
  assert.ok(analyzeImplementation(root, defaults, lib).errors.length);
  const completed = replaceSelection(defaults, ['child'], { relationship: 'end', submodels: {} });
  assert.deepEqual(analyzeImplementation(root, completed, lib).errors, []);
});
