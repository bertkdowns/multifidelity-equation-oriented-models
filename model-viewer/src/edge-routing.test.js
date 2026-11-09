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

test('summary replacements use top/bottom and remain orthogonal under every unit orientation', async () => {
  const {summaryPortGeometry} = await import('./edge-routing.js');
  const axis = side => ['top','bottom'].includes(side) ? 'vertical' : 'horizontal';
  for (const flipped of [false,true]) for (const rotation of [0,1,2,3]) {
    const data = {kind:'model',flipped,rotation};
    for (const type of ['source','target']) {
      const process=summaryPortGeometry({type,top:'30%'},data);
      const feedback=summaryPortGeometry({type,top:'30%',replacement:true},data);
      assert.notEqual(axis(process.side),axis(feedback.side));
      if (rotation===0) assert.equal(feedback.side,type==='source'?'top':'bottom');
      assert.ok(Object.values(feedback.style).every(value=>parseFloat(value)>0 && parseFloat(value)<100));
    }
    const start=summaryPortGeometry({type:'source',top:'30%',replacement:true},data);
    const end=summaryPortGeometry({type:'target',top:'60%',replacement:true,feedback:true},data);
    assert.equal(start.side,end.side);
    assert.notDeepEqual(start.style,end.style);
  }
  assert.deepEqual(summaryPortGeometry({type:'source',top:'30%',replacement:true},{kind:'model',rotation:1}),{side:'right',style:{top:'30%'}});
});
