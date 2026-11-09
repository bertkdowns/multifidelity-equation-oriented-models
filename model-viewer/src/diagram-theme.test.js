import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadArrowVisibility, saveArrowVisibility, visibleEdges } from './diagram-theme.js';

test('arrow controls restore saved booleans and tolerate invalid or unavailable storage', () => {
  let value = null;
  const storage = { getItem: () => value, setItem: (_, next) => { value = next; } };
  const defaults = { connection: true, dependency: true, replacement: true };
  assert.deepEqual(loadArrowVisibility(storage), defaults);
  const settings = { connection: false, dependency: true, replacement: false };
  saveArrowVisibility(settings, storage);
  assert.deepEqual(loadArrowVisibility(storage), settings);
  value = '{"connection":false,"dependency":"false"}';
  assert.deepEqual(loadArrowVisibility(storage), { ...defaults, connection: false });
  value = '{';
  assert.deepEqual(loadArrowVisibility(storage), defaults);
  const blocked = { getItem() { throw Error('blocked'); }, setItem() { throw Error('blocked'); } };
  assert.deepEqual(loadArrowVisibility(blocked), defaults);
  assert.doesNotThrow(() => saveArrowVisibility(settings, blocked));
});

test('dependency control hides both equation directions without changing graph endpoints', () => {
  const edges = ['connection', 'dependency', 'determines', 'replacement'].map(kind => ({ id: kind, source: 'a', target: 'b', data: { kind } }));
  const hidden = visibleEdges(edges, { connection: true, dependency: false, replacement: true });
  assert.deepEqual(hidden.map(edge => edge.hidden), [false, true, true, false]);
  assert.ok(edges.every(edge => !Object.hasOwn(edge, 'hidden')));
  assert.deepEqual(visibleEdges(hidden, { dependency: true }).map(edge => edge.hidden), [false, false, false, false]);
});
