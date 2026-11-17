import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { makeGraph, resolveReference, variableLabel } from './graph.js';

const directory = new URL('../../src/multifidelity/model_language/blocks/', import.meta.url);
const registry = Object.fromEntries(readdirSync(directory).filter(name => name.endsWith('.json')).map(name => {
  const model = JSON.parse(readFileSync(new URL(name, directory), 'utf8'));
  return [model.id, model];
}));

test('every formulation renders all declarations and valid edge endpoints', () => {
  for (const definition of Object.values(registry)) {
    for (const [name, formulation] of Object.entries(definition.formulations)) {
      const graph = makeGraph({ definition, bindings: {} }, name, registry);
      assert.equal(graph.nodes.length, Object.keys(definition.structs).length + Object.keys(formulation.blocks ?? {}).length + Object.keys(formulation.constraints ?? {}).length + Object.keys(formulation.derivatives ?? {}).length);
      const ids = new Set(graph.nodes.map(node => node.id));
      for (const edge of graph.edges) {
        assert.ok(ids.has(edge.source)); assert.ok(ids.has(edge.target));
        for (const [id, handle] of [[edge.source, edge.sourceHandle], [edge.target, edge.targetHandle]]) {
          const data = graph.nodes.find(node => node.id === id).data;
          const port = handle.replace(/:(in|out)$/, '');
          assert.ok(port === 'equation' || data.rows.some(row => port === row.name || Object.keys(row.variables).some(variable => port === `${row.name}.${variable}`)), `${definition.id}/${name}: missing ${handle}`);
        }
      }
      assert.ok(!graph.warnings.some(warning => warning.startsWith('Cannot resolve')), `${definition.id}/${name}: ${graph.warnings}`);
    }
  }
});

test('concrete wrapper binds generics through drill down', () => {
  const wrapper = registry.pump_flowsheet;
  const pump = resolveReference(wrapper.formulations.flowsheet.blocks.pump, {}, registry);
  const graph = makeGraph(pump, 'incompressible', registry);
  assert.deepEqual(graph.warnings, []);
  assert.equal(graph.nodes.find(node => node.id === 'block:outlet_state').data.child.definition.id, 'state_block');
  const energy = graph.edges.filter(edge => edge.source === 'constraint:energy_balance');
  assert.equal(energy.length, 1);
  assert.equal(energy[0].targetHandle, 'outlet.enthalpy:in');
});

test('struct connections can read a parent outlet to supply a child state input', () => {
  const pump = resolveReference(registry.pump_flowsheet.formulations.flowsheet.blocks.pump, {}, registry);
  const graph = makeGraph(pump, 'incompressible', registry);
  const edge = graph.edges.find(edge => edge.id === 'connection:outlet_state');
  assert.equal(edge.source, 'struct:outlet');
  assert.equal(edge.target, 'block:outlet_state');
  assert.equal(edge.sourceHandle, 'outlet:out');
  assert.equal(edge.targetHandle, 'state:in');
  assert.deepEqual(graph.warnings, []);
});

test('summary gives every edge a distinct, evenly spaced attachment on each side', () => {
  const pump = resolveReference(registry.pump_flowsheet.formulations.flowsheet.blocks.pump, {}, registry);
  const graph = makeGraph(pump, 'incompressible', registry, 'summary');
  for (const node of graph.nodes) {
    for (const type of ['source', 'target']) {
      const ports = node.data.summaryPorts.filter(port => port.type === type);
      assert.equal(new Set(ports.map(port => port.top)).size, ports.length);
      const edges = graph.edges.filter(edge => edge[type] === node.id);
      assert.equal(ports.length, edges.length);
      for (const edge of edges) {
        assert.ok(ports.some(port => port.id === edge[`${type}Handle`]));
        assert.ok(edge.data[`${type}Port`]);
      }
    }
  }
});

test('summary heat exchanger ports follow struct order even when connections are reversed', () => {
  const definition = {
    id: 'port_order_fixture', structs: {}, formulations: {
      flowsheet: { blocks: { exchanger: { block: 'heat_exchanger' }, other: { block: 'heat_exchanger' } }, constraints: {}, connections: {
        cold_in: { from: 'other.cold_outlet', to: 'exchanger.cold_inlet' },
        hot_in: { from: 'other.hot_outlet', to: 'exchanger.hot_inlet' },
        cold_out: { from: 'exchanger.cold_outlet', to: 'other.cold_inlet' },
        hot_out: { from: 'exchanger.hot_outlet', to: 'other.hot_inlet' },
      } },
    },
  };
  const graph = makeGraph({ definition, bindings: {} }, 'flowsheet', registry, 'summary');
  const node = graph.nodes.find(node => node.id === 'block:exchanger');
  for (const [type, expected] of [['target', ['hot_inlet:in', 'cold_inlet:in']], ['source', ['hot_outlet:out', 'cold_outlet:out']]]) {
    const ordered = node.data.summaryPorts.filter(port => port.type === type).map(port => {
      const edge = graph.edges.find(edge => edge[type] === node.id && edge[`${type}Handle`] === port.id);
      return edge.data[`${type}Port`];
    });
    assert.deepEqual(ordered, expected);
  }
});

test('dynamic tank connects indexed equations and both derivative relations without unresolved ports', () => {
  for (const view of ['summary', 'detailed']) {
    const graph = makeGraph(resolveReference(registry.tank_flowsheet.formulations.flowsheet.blocks.tank, {}, registry), 'mixed', registry, view);
    assert.deepEqual(graph.warnings, []);
    const derivative = graph.nodes.find(node => node.id === 'constraint:derivative:mass');
    assert.equal(derivative.data.equation.derivative.with_respect_to, 'time');
    const output = graph.edges.find(edge => edge.id === 'constraint:derivative:mass:determines');
    assert.equal(output.target, 'struct:inventory');
    const balanceOutput = graph.edges.find(edge => edge.id === 'constraint:mass_balance:determines');
    assert.equal(balanceOutput.target, 'struct:rates');
    assert.equal(balanceOutput.label, 'rates.mass[t]');
    assert.ok(!graph.edges.some(edge => edge.source === 'struct:rates' && edge.target === 'constraint:mass_balance'));
  }
  assert.equal(variableLabel('flow', { dimensions: ['time', 'components'] }), 'flow[time, components]');
  assert.equal(variableLabel('area', {}), 'area');
});

test('multi-index child references connect to families and preserve domain bindings on drill down', () => {
  const variable = { dimensions: ['time', 'components'], unit: 'kg/s' };
  const child = { id: 'indexed_child', domains: { time: { kind: 'time' }, components: { kind: 'discrete' } }, structs: { inlet: { direction: 'input', variables: { flow: variable } } }, formulations: {} };
  const definition = { id: 'indexed_parent', structs: { feed: { direction: 'input', variables: { flow: variable } } }, formulations: { evaluate: { blocks: { pipe: { block: child.id, domain_bindings: { time: 'clock', components: 'species' } } }, constraints: { feed: { for_each: { t: 'clock', j: 'species' }, lhs: 'pipe.inlet.flow[t, j]', rhs: 'feed.flow[t, j]', determines: 'pipe.inlet.flow[t, j]' } } } } };
  const graph = makeGraph({ definition, bindings: {} }, 'evaluate', { indexed_child: child });
  assert.deepEqual(graph.warnings, []);
  assert.equal(graph.edges.find(edge => edge.id === 'constraint:feed:determines').targetHandle, 'inlet.flow:in');
  assert.deepEqual(graph.nodes.find(node => node.id === 'block:pipe').data.child.domainBindings, { time: 'clock', components: 'species' });
});
