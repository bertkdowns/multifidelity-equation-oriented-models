import { test } from 'node:test';
import assert from 'node:assert/strict';
import { routeDetailedEdges } from './edge-routing.js';
const edge = { id: 'e', source: 'input', target: 'constraint', sourceHandle: 'feed.pressure:out', targetHandle: 'equation:in', data: { kind: 'dependency' } };
const node = (id, x, summary = false) => ({ id, position: { x, y: 0 }, data: { width: 300, summary } });

test('detailed arrows choose facing sides and preserve logical endpoints as nodes cross', () => {
  const right = routeDetailedEdges([node('input', 0), node('constraint', 500)], [edge])[0];
  assert.equal(right.sourceHandle, 'feed.pressure:out');
  assert.equal(right.targetHandle, 'equation:in');
  const left = routeDetailedEdges([node('input', 600), node('constraint', 0)], [edge])[0];
  assert.equal(left.sourceHandle, 'feed.pressure:out-left');
  assert.equal(left.targetHandle, 'equation:in-right');
  assert.equal(left.source, 'input');
  assert.equal(left.target, 'constraint');
  assert.equal(left.data.sourcePort, 'feed.pressure:out');
});

test('summary ports retain their explicit orientation', () => {
  assert.equal(routeDetailedEdges([node('input', 600, true), node('constraint', 0, true)], [edge])[0], edge);
});
