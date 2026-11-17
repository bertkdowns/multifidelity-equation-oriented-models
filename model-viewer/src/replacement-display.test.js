import {test} from 'node:test';
import assert from 'node:assert/strict';
import {displayedValues, replacementPairs, replacementCell} from './replacement-display.js';
import {makeGraph, resolveReference} from './graph.js';
import {routeDetailedEdges} from './edge-routing.js';
import {readFileSync, readdirSync} from 'node:fs';

const directory=new URL('../../src/multifidelity/model_language/blocks/',import.meta.url);
const registry=Object.fromEntries(readdirSync(directory).filter(name=>name.endsWith('.json')).map(name=>{
  const definition=JSON.parse(readFileSync(new URL(name,directory),'utf8'));return [definition.id,definition];
}));
const records=[{tag:'chosen',variable_path:'outlet.pressure',value:200,unit:'kPa'}];
const parameters={parameters:['chosen'],replacements:{chosen:'parameters.pressure_drop'}};
const context={definition:registry.valve,bindings:{}};

test('saved records resolve fixed-to-replaced direction, without inferring missing data',()=>{
  assert.deepEqual(replacementPairs(parameters,records),{pairs:[{recordTag:'chosen',from:'outlet.pressure',to:'parameters.pressure_drop'}],warnings:[]});
  assert.equal(replacementPairs(parameters,[]).warnings.length,1);
  assert.deepEqual(replacementPairs(null,records),{pairs:[],warnings:[]});
});

test('detailed feedback arrows point to input handles and do not alter process layout',()=>{
  const plain=makeGraph(context,'isenthalpic',registry);
  const graph=makeGraph(context,'isenthalpic',registry,'detailed',replacementPairs(parameters,records).pairs);
  const edge=graph.edges.find(edge=>edge.data.kind==='replacement');
  assert.equal(edge.source,'struct:outlet');assert.equal(edge.target,'struct:parameters');
  assert.equal(edge.sourceHandle,'outlet.pressure:out');assert.equal(edge.targetHandle,'parameters.pressure_drop:in');
  assert.equal(edge.markerEnd.type,'arrow');assert.equal(edge.style.stroke,'#c06616');assert.ok(edge.style.strokeDasharray);
  assert.deepEqual(graph.nodes.map(node=>node.position),plain.nodes.map(node=>node.position));
});

test('descendant pairs trace to visible blocks and drill down to variable rows',()=>{
  const root={definition:registry.heat_pump_flowsheet,bindings:{}};
  const pair={recordTag:'temperature',from:'heat_pump.sink_inlet_state.properties.temperature',to:'heat_pump.sink_inlet.enthalpy'};
  const graph=makeGraph(root,'flowsheet',registry,'detailed',[pair]);
  const edge=graph.edges.find(edge=>edge.data.kind==='replacement');
  assert.equal(edge.source,'block:heat_pump');assert.equal(edge.target,'block:heat_pump');
  assert.ok(graph.nodes.find(node=>node.id===edge.source).data.replacementPorts.includes('replacement:heat_pump.sink_inlet_state.properties.temperature'));
  const routed=routeDetailedEdges(graph.nodes,graph.edges).find(edge=>edge.data.kind==='replacement');
  assert.ok(routed.targetHandle.endsWith(':in-right'));
  const child=resolveReference(root.definition.formulations.flowsheet.blocks.heat_pump,{},registry);
  const nested=makeGraph(child,'aggregate',registry,'detailed',[pair],'heat_pump');
  const nestedEdge=nested.edges.find(edge=>edge.data.kind==='replacement');
  assert.equal(nestedEdge.source,'block:sink_inlet_state');
  assert.equal(nestedEdge.sourceHandle,'properties.temperature:out');
  assert.equal(nestedEdge.target,'struct:sink_inlet');
  assert.equal(nestedEdge.targetHandle,'sink_inlet.enthalpy:in');
  const local=makeGraph(context,'isenthalpic',registry,'detailed',[
    {recordTag:'a',from:'unit.outlet.pressure',to:'unit.parameters.pressure_drop'},
    {recordTag:'external',from:'other.outlet.pressure',to:'unit.inlet.pressure'},
  ],'unit');
  assert.equal(local.edges.filter(edge=>edge.data.kind==='replacement').length,1);
  assert.equal(local.edges.find(edge=>edge.data.kind==='replacement').targetHandle,'parameters.pressure_drop:in');
});

test('summary feedback ends get distinct ports and stay attached through rotation',()=>{
  const pair={recordTag:'inside',from:'heat_pump.sink_inlet_state.properties.temperature',to:'heat_pump.sink_inlet.enthalpy'};
  const graph=makeGraph({definition:registry.heat_pump_flowsheet,bindings:{}},'flowsheet',registry,'summary',[pair]);
  const edge=graph.edges.find(edge=>edge.data.kind==='replacement');
  const node=graph.nodes.find(node=>node.id===edge.source);
  const start=node.data.summaryPorts.find(port=>port.id===edge.sourceHandle);
  const end=node.data.summaryPorts.find(port=>port.id===edge.targetHandle);
  assert.equal(end.feedback,true);assert.notEqual(start.top,end.top);
  assert.equal(routeDetailedEdges(graph.nodes,graph.edges).find(e=>e.id===edge.id),edge);
});

test('green resources replaces blue inline values and respects the selected record',()=>{
  const preferred={tag:'high-trust',value:3};
  const selected={tag:'chosen',value:2};
  const solved={entries:[{value:2,fixed:true}]};
  assert.deepEqual(displayedValues([preferred,selected],solved,new Set(['chosen'])),{record:selected,result:undefined});
  assert.deepEqual(displayedValues([preferred],solved),{record:preferred,result:undefined});
  assert.deepEqual(displayedValues([],solved),{record:undefined,result:solved});
});


test('fixed noncanonical result rows name replaced inputs, without annotating free values',()=>{
  const pairs=replacementPairs(parameters,records).pairs;
  const fixed={variable_path:'outlet.pressure',entries:[{fixed:true}]};
  assert.equal(replacementCell(fixed,pairs,new Set()),'parameters.pressure_drop');
  assert.equal(replacementCell({...fixed,entries:[{fixed:false}]},pairs,new Set()),'—');
  assert.equal(replacementCell({...fixed,variable_path:'inlet.pressure'},pairs,new Set(['inlet.pressure'])),'Direct input');
  assert.equal(replacementCell(fixed,[],new Set()),'Not recorded');
  assert.equal(replacementCell({...fixed,entries:[{fixed:true},{fixed:false}]},[],new Set(),new Set(['outlet.pressure'])),'Initial condition');
});
