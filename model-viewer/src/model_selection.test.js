import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { defaultModel, parseModel, analyzeModel, selectionAt, replaceSelection } from './model_selection.js';
import { resolveReference } from './graph.js';
const dir = new URL('../../src/multifidelity/model_language/blocks/', import.meta.url);
const library = Object.fromEntries(readdirSync(dir).filter(name => name.endsWith('.json')).map(name => {
  const model = JSON.parse(readFileSync(new URL(name, dir), 'utf8')); return [model.id, model];
}));
const context = id => ({ definition: library[id], bindings: {} });
const example = path => parseModel(readFileSync(new URL(`../../examples/${path}`, import.meta.url), 'utf8'));

test('SGHP alternative combinations produce expected heat-pump subtree inputs and portable round trips', () => {
  for (const [name, expected] of [['aggregate_aggregate', 5], ['aggregate_cycle', 10], ['cycle_aggregate', 10], ['cycle_cycle', 15]]) {
    const catalog = example(`steam_generating_heat_pump_system/${name}.json`);
    const result = analyzeModel(context('steam_generating_heat_pump_system'), catalog, library);
    assert.deepEqual(result.errors, []);
    assert.equal(result.inputs.filter(input => input.path.startsWith('sghp.') || input.path.startsWith('phnix.')).length, expected);
    assert.deepEqual(parseModel(JSON.stringify(catalog)), catalog);
    assert.ok(!('block' in catalog));
  }
});

test('changing a child prunes stale descendants, preserves siblings and updates inputs', () => {
  const root = context('steam_generating_heat_pump_system');
  const original = defaultModel(root, library);
  const sghp = resolveReference(root.definition.formulations.flowsheet.blocks.sghp, {}, library);
  const cycle = defaultModel(sghp, library, 'cycle');
  const changed = replaceSelection(original, ['sghp'], cycle);
  assert.equal(selectionAt(changed, ['sghp']).formulation, 'cycle');
  assert.equal(selectionAt(original, ['sghp']).formulation, 'aggregate');
  assert.equal(changed.subblocks.phnix, original.subblocks.phnix);
  assert.ok(!changed.subblocks.sghp.subblocks.cop_model);
  const result = analyzeModel(root, changed, library);
  assert.deepEqual(result.errors, []);
  assert.equal(result.inputs.length - analyzeModel(root, original, library).inputs.length, 5);
});

test('input requirements exclude supplied child fields, retaining partial structs and generic children', () => {
  const catalog = example('model_language/pump_flowsheet.json');
  const result = analyzeModel(context('pump_flowsheet'), catalog, library);
  assert.deepEqual(result.errors, []);
  assert.equal(result.inputs.length, 5);
  assert.ok(result.inputs.some(item => item.path === 'pump.inlet.pressure'));
  assert.ok(!result.inputs.some(item => item.path.includes('outlet_state') && item.name === 'pressure'));
  assert.ok(!result.inputs.some(item => item.path.includes('coefficients')));
});

test('dynamic initial families are reported separately from inputs', () => {
  const catalog = example('model_language/tank_mixed.json');
  const result = analyzeModel(context('tank_flowsheet'), catalog, library);
  assert.deepEqual(result.errors, []);
  assert.equal(result.inputs.length, 7);
  assert.deepEqual(result.initial.map(item => item.path).sort(), ['tank.inventory.energy', 'tank.inventory.mass']);
});

test('upload rejects malformed shape, wrong formulations and stale child aliases', () => {
  for (const catalog of [null, [], { block: 'valve', formulation: 'isenthalpic' }, { formulation: '' }, { formulation: 'x', subblocks: [] }])
    assert.throws(() => parseModel(JSON.stringify(catalog)));
  assert.throws(() => parseModel('{broken'));
  const wrong = analyzeModel(context('valve'), { formulation: 'bad' }, library);
  assert.ok(wrong.errors.some(message => message.includes('valid formulation')));
  const stale = analyzeModel(context('valve'), { formulation: 'isenthalpic', subblocks: { stale: { formulation: 'a' } } }, library);
  assert.ok(stale.errors.some(message => message.includes('subblocks must be exactly')));
});

test('recursive defaults stop and allow an explicit terminating formulation', () => {
  const recursive = { id: 'recursive', structs: {}, formulations: { recur: { blocks: { child: { block: 'recursive' } } }, end: {} } };
  const root = { definition: recursive, bindings: {} };
  const lib = { recursive };
  const defaults = defaultModel(root, lib);
  assert.equal(defaults.subblocks.child.formulation, '');
  assert.ok(analyzeModel(root, defaults, lib).errors.length);
  const completed = replaceSelection(defaults, ['child'], { formulation: 'end', subblocks: {} });
  assert.deepEqual(analyzeModel(root, completed, lib).errors, []);
});
