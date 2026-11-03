import { test } from 'node:test';
import assert from 'node:assert/strict';
import { layoutKey, restorePositions, savePositions } from './layout-storage.js';

function memoryStorage() {
  const values = new Map();
  return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
}
const nodes = [{ id: 'model:pump', position: { x: 10, y: 20 } }, { id: 'constraint:mass', position: { x: 30, y: 40 } }];

test('layout identity is shared by occurrences and separated by model, relationship and view', () => {
  const storage = memoryStorage();
  const key = layoutKey('pump', 'incompressible', 'summary');
  const moved = nodes.map(node => ({ ...node, position: { x: node.position.x + 100, y: node.position.y - 80 } }));
  savePositions(moved, key, storage);
  assert.deepEqual(restorePositions(nodes, layoutKey('pump', 'incompressible', 'summary'), storage), moved);
  for (const other of [layoutKey('pump', 'incompressible', 'detailed'), layoutKey('pump', 'other', 'summary'), layoutKey('valve', 'incompressible', 'summary')]) {
    assert.deepEqual(restorePositions(nodes, other, storage), nodes);
  }
  const newNode = { id: 'model:new', position: { x: 1, y: 2 } };
  assert.deepEqual(restorePositions([newNode, nodes[0]], key, storage), [newNode, moved[0]]);
});

test('corrupt or unavailable storage and invalid coordinates preserve automatic positions', () => {
  const storage = memoryStorage();
  for (const value of ['{broken', 'null', '{"model:pump":{"x":"bad","y":1}}']) {
    storage.setItem('key', value);
    assert.deepEqual(restorePositions(nodes, 'key', storage), nodes);
  }
  const unavailable = { getItem() { throw Error('disabled'); }, setItem() { throw Error('full'); } };
  assert.deepEqual(restorePositions(nodes, 'key', unavailable), nodes);
  assert.doesNotThrow(() => savePositions(nodes, 'key', unavailable));
});

test('orientations survive saving, group moves and reopening without breaking old layouts', () => {
  const storage = memoryStorage();
  const key = layoutKey('heat_exchanger', 'lumped', 'summary');
  const oriented = nodes.map((node, index) => ({ ...node, data: { flipped: index === 0, rotation: index + 2 } }));
  savePositions(oriented, key, storage);
  const restored = restorePositions(nodes, key, storage);
  assert.deepEqual(restored, oriented);
  const moved = restored.map(node => ({ ...node, position: { x: 99, y: 88 } }));
  savePositions(moved, key, storage);
  assert.deepEqual(restorePositions(nodes, key, storage), moved);
  storage.setItem(key, JSON.stringify({ 'model:pump': { x: 1, y: 2, rotation: 999, flipped: 'yes' } }));
  assert.deepEqual(restorePositions(nodes, key, storage)[0], { ...nodes[0], position: { x: 1, y: 2 } });
});
