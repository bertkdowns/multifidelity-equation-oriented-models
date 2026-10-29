import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { makeGraph, resolveReference } from './graph.js';

const directory = new URL('../../src/multifidelity/model_language/models/', import.meta.url);
const library = Object.fromEntries(readdirSync(directory).filter(name => name.endsWith('.json')).map(name => {
  const model = JSON.parse(readFileSync(new URL(name, directory), 'utf8'));
  return [model.id, model];
}));

test('every relationship renders all declarations and valid edge endpoints', () => {
  for (const definition of Object.values(library)) {
    for (const [name, relationship] of Object.entries(definition.relationships)) {
      const graph = makeGraph({ definition, bindings: {} }, name, library);
      assert.equal(graph.nodes.length, Object.keys(definition.structs).length + Object.keys(relationship.models ?? {}).length + Object.keys(relationship.constraints ?? {}).length);
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
  const wrapper = library.pump_flowsheet;
  const pump = resolveReference(wrapper.relationships.flowsheet.models.pump, {}, library);
  const graph = makeGraph(pump, 'incompressible', library);
  assert.deepEqual(graph.warnings, []);
  assert.equal(graph.nodes.find(node => node.id === 'model:outlet_state').data.child.definition.id, 'water_property_package');
  const energy = graph.edges.filter(edge => edge.source === 'constraint:energy_balance');
  assert.equal(energy.length, 1);
  assert.equal(energy[0].targetHandle, 'outlet.enthalpy:in');
});

test('struct connections preserve source and destination ports', () => {
  const graph = makeGraph({ definition: library.property_pair, bindings: {} }, 'evaluate', library);
  const edge = graph.edges.find(edge => edge.id === 'connection:inlet_state');
  assert.equal(edge.source, 'struct:inlet_state');
  assert.equal(edge.target, 'model:inlet');
  assert.equal(edge.targetHandle, 'state:in');
  assert.equal(graph.warnings.length, 2);
});

test('summary gives every edge a distinct, evenly spaced attachment on each side', () => {
  const pump = resolveReference(library.pump_flowsheet.relationships.flowsheet.models.pump, {}, library);
  const graph = makeGraph(pump, 'incompressible', library, 'summary');
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
