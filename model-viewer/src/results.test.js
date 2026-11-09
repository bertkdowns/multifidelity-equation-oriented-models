import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {parseResults,indexResults,resultNumber,resultPreview,sameImplementation,fixedFirst} from './results.js';
const fixture=()=>({schema_version:1,run_id:'run-1',created_at:'2026-11-05T00:00:00Z',model_id:'valve',implementation:{relationship:'isenthalpic',submodels:{}},mode:'steady',time_unit:'s',solve:{status:'optimal',termination_condition:'optimal'},variables:[{variable_path:'inlet.pressure',unit:'Pa',dimensions:['time'],entries:[{index:[0],value:200000,fixed:true,issue:null}]}]});

test('actual Python SGHP export loads with occurrence paths and fixed/free values',()=>{
  const doc=parseResults(readFileSync(new URL('../../examples/steam_generating_heat_pump_system/results.json',import.meta.url),'utf8'));
  assert.equal(doc.model_id,'steam_generating_heat_pump_system');
  assert.equal(doc.solve.status,'optimal');
  const index=indexResults(doc);
  assert.equal(index.get('sghp.cop_model.parameters.cop').entries[0].value,4);
  assert.equal(index.get('sghp.cop_model.parameters.cop').entries[0].fixed,true);
  assert.equal(index.get('steam_outlet.flow').entries[0].fixed,false);
  assert.ok(doc.variables.length>100);
});

test('coordinates retain types and multidimensional entries are not flattened',()=>{
  const doc=fixture();doc.mode='dynamic';doc.variables[0].dimensions=['time','zone'];
  doc.variables[0].entries=[{index:[0,'A'],value:2,fixed:true},{index:[10,'B'],value:null,fixed:false,issue:'unset'}];
  const parsed=parseResults(JSON.stringify(doc)),variable=parsed.variables[0];
  assert.deepEqual(variable.entries[1].index,[10,'B']);
  assert.equal(resultNumber(variable.entries[1]),'Unavailable (unset)');
  assert.equal(resultPreview(variable),'2 indexed values');
  doc.variables[0].dimensions=[];doc.variables[0].entries=[{index:[],value:2,fixed:false}];
  assert.equal(parseResults(JSON.stringify(doc)).variables[0].entries[0].index.length,0);
});

test('malformed snapshots and diagnostic-report files are rejected',()=>{
  const mutations=[d=>d.schema_version=2,d=>d.model_id='',d=>d.created_at='yesterday',d=>d.solve.status='probably good',d=>d.variables.push(d.variables[0]),d=>d.variables[0].entries.push(d.variables[0].entries[0]),d=>d.variables[0].entries[0].index=[true],d=>d.variables[0].entries[0].index=[],d=>d.variables[0].entries[0].value='3',d=>d.variables[0].entries[0].value=null,d=>d.variables[0].entries[0].fixed='yes',d=>d.variables[0].entries[0].issue='unset',d=>d.extra='unexpected',d=>d.variables[0].dimensions=['time','time']];
  for(const mutate of mutations){const doc=fixture();mutate(doc);assert.throws(()=>parseResults(JSON.stringify(doc)));}
  assert.throws(()=>parseResults(JSON.stringify({success:true,stages:[]})));
});

test('failed snapshots stay failed and implementation comparison ignores object ordering',()=>{
  const doc=fixture();doc.solve.status='failed';assert.equal(parseResults(JSON.stringify(doc)).solve.status,'failed');
  assert.ok(sameImplementation({relationship:'r',submodels:{a:{relationship:'x'},b:{relationship:'y'}}},{relationship:'r',submodels:{b:{relationship:'y',submodels:{}},a:{relationship:'x'}}}));
  assert.ok(!sameImplementation({relationship:'r'},{relationship:'x'}));
  assert.ok(!sameImplementation({relationship:'r'},{relationship:'r',submodels:{a:{relationship:'x'}}}));
});


test('tables show fixed then mixed then free, preserving order within groups and the saved snapshot', () => {
  const free={id:'free',entries:[{fixed:false}]};
  const fixedA={id:'a',entries:[{fixed:true}]};
  const fixedB={id:'b',entries:[{fixed:true},{fixed:true}]};
  const mixed={id:'mixed',entries:[{fixed:false},{fixed:true}]};
  const original=[free,fixedA,mixed,fixedB];
  assert.deepEqual(fixedFirst(original).map(item=>item.id),['a','b','mixed','free']);
  assert.deepEqual(original,[free,fixedA,mixed,fixedB]);
  assert.deepEqual(fixedFirst(mixed.entries).map(entry=>entry.fixed),[true,false]);
  assert.deepEqual(mixed.entries.map(entry=>entry.fixed),[false,true]);
});

test('replacement pairs survive result loading and malformed pair maps are rejected', () => {
  const doc=fixture();
  doc.specification={specifications:['temperature'],replacements:{temperature:'state.enthalpy'},initial_values:[]};
  assert.deepEqual(parseResults(JSON.stringify(doc)).specification.replacements,{temperature:'state.enthalpy'});
  for (const replacements of [null,[],{missing:'state.enthalpy'},{temperature:''},{temperature:3}]) {
    doc.specification.replacements=replacements;
    assert.throws(()=>parseResults(JSON.stringify(doc)));
  }
  doc.specification.specifications=['a','b'];
  doc.specification.replacements={a:'state.enthalpy',b:'state.enthalpy'};
  assert.throws(()=>parseResults(JSON.stringify(doc)));
});
