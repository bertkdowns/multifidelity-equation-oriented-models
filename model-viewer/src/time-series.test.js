import { test } from 'node:test';
import assert from 'node:assert/strict';
import { timeSeries, timeDomainsByOccurrence, timeDimensionForVariable, plotGeometry } from './time-series.js';

test('uses actual numeric times, preserving gaps, zero values and fixity', () => {
  const variable = { variable_path: 'tank.outlet.temperature', dimensions: ['clock'], entries: [
    { index: [20], value: 5, fixed: false }, { index: [0], value: 0, fixed: true },
    { index: [2], value: null, fixed: false, issue: 'unset' },
  ] };
  const [series] = timeSeries(variable, 'clock');
  assert.deepEqual(series.points.map(point => point.time), [0, 2, 20]);
  assert.equal(series.points[0].value, 0);
  assert.equal(series.points[0].fixed, true);
  assert.equal(series.points[1].issue, 'unset');
  assert.deepEqual(variable.entries.map(entry => entry.index[0]), [20, 0, 2]);
  const geometry = plotGeometry(series.points);
  assert.equal((geometry.path.match(/M/g) ?? []).length, 2);
  assert.ok(!geometry.path.includes('L'));
  assert.equal(geometry.firstTime, 0);
  assert.equal(geometry.lastTime, 20);
  assert.ok(Math.abs(geometry.x(2) - geometry.left - 0.1 * (geometry.right - geometry.left)) < 1e-8);
});

test('non-time dimensions produce separate selectable series in declared order', () => {
  const variable = { dimensions: ['zone', 'clock', 'component'], entries: [
    { index: ['A', 10, 'water'], value: 3 }, { index: ['B', 0, 'water'], value: 4 },
    { index: ['A', 0, 'water'], value: 1 }, { index: ['A', 0, 'air'], value: 8 },
  ] };
  const series = timeSeries(variable, 'clock');
  assert.equal(series.length, 3);
  assert.equal(series[0].label, 'zone="A", component="water"');
  assert.deepEqual(series[0].points.map(point => point.value), [1, 3]);
  assert.equal(series[1].label, 'zone="B", component="water"');
});

test('time domains come from model declarations instead of dimension naming guesses', () => {
  const domains = timeDomainsByOccurrence({ occurrences: [
    { path: [], context: { definition: { domains: { clock: { kind: 'time' } } } } },
    { path: ['a'], context: { definition: { domains: { local: { kind: 'time' }, time: { kind: 'discrete' } } } } },
  ] });
  assert.equal(timeDimensionForVariable({ variable_path: 'outlet.x', dimensions: ['clock'] }, domains), 'clock');
  assert.equal(timeDimensionForVariable({ variable_path: 'a.outlet.x', dimensions: ['local'] }, domains), 'local');
  assert.equal(timeDimensionForVariable({ variable_path: 'a.outlet.x', dimensions: ['time'] }, domains), undefined);
});

test('flat, single-point and unavailable series do not produce invalid plot coordinates', () => {
  for (const points of [[{ time: 0, value: 0 }], [{ time: 0, value: 200000 }, { time: 100, value: 200000 }]]) {
    const plot = plotGeometry(points);
    assert.ok(plot.max > plot.min);
    assert.ok(!/NaN|Infinity/.test(plot.path));
  }
  assert.equal(plotGeometry([{ time: 0, value: null }]), null);
  assert.deepEqual(timeSeries({ dimensions: [], entries: [{ index: [], value: 1 }] }, 'clock'), []);
  assert.deepEqual(timeSeries({ dimensions: ['clock'], entries: [{ index: ['unknown'], value: 1 }] }, 'clock'), []);
});
