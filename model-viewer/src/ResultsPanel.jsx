import React, {useEffect,useMemo,useState} from 'react';
import TimeSeriesChart from './TimeSeriesChart.jsx';
import {timeDomainsByOccurrence, timeDimensionForVariable} from './time-series.js';
import {analyzeModel} from './model_selection.js';
import {findVariable} from './resources.js';
import {replacementPairs, replacementCell} from './replacement-display.js';
import {parseResults,resultNumber,resultPreview,sameModel,fixedFirst} from './results.js';

export function ResultValues({variable,mode,timeDimension,timeUnit}) {
  return <div className="result-values"><p><code>{variable.variable_path}</code> · {variable.unit}</p>{mode === 'dynamic' && timeDimension && <TimeSeriesChart variable={variable} timeDimension={timeDimension} timeUnit={timeUnit}/>}<table className="resources-table"><thead><tr><th>Coordinates {variable.dimensions.length ? `(${variable.dimensions.join(', ')})` : '(scalar)'}</th><th>Value</th><th>State at export</th></tr></thead><tbody>{fixedFirst(variable.entries).map(entry=><tr key={JSON.stringify(entry.index)}><td>{JSON.stringify(entry.index)}</td><td>{resultNumber(entry)}</td><td>{entry.fixed ? 'Fixed' : 'Free'}</td></tr>)}</tbody></table></div>;
}
export default function ResultsPanel({root,file,model_document,registry,resources=[],onChange,onClear,onUseModel}) {
  const [error,setError]=useState(''),[loading,setLoading]=useState(false),[search,setSearch]=useState(''),[url,setUrl]=useState('');
  const doc=file?.catalog;
  const analysis=useMemo(()=>doc ? analyzeModel(root,doc.model_document,registry) : null,[root,doc,registry]);
  const timeDomains=useMemo(()=>timeDomainsByOccurrence(analysis),[analysis]);
  const replacements=useMemo(()=>replacementPairs(doc?.parameters,resources),[doc,resources]);
  const canonicalPaths=useMemo(()=>new Set((analysis?.inputs ?? []).map(input=>input.path)),[analysis]);
  const initialPaths=useMemo(()=>new Set(resources.filter(record=>(doc?.parameters?.initial_values ?? []).includes(record.tag)).map(record=>record.variable_path)),[doc,resources]);
  const savedPaths=useMemo(()=>{
    const paths=new Set();
    for (const occurrence of analysis?.occurrences ?? []) for (const [name,struct] of Object.entries(occurrence.context.definition.structs)) for (const field of Object.keys(struct.variables)) paths.add([...occurrence.path,name,field].join('.'));
    return paths;
  },[analysis]);
  useEffect(()=>{
    if (!doc) {setUrl('');return;}
    const next=URL.createObjectURL(new Blob([JSON.stringify(doc,null,2)+'\n'],{type:'application/json'}));setUrl(next);return()=>URL.revokeObjectURL(next);
  },[doc]);
  async function load(upload) {
    if (!upload || loading) return;
    setLoading(true);setError('');
    try {
      if (upload.size>20*1024*1024) throw Error('Please use a results file smaller than 20 MB.');
      const catalog=parseResults(await upload.text());
      if (!registry[catalog.block_id]) throw Error(`Model ${catalog.block_id} is not in this registry.`);
      onChange({name:upload.name,catalog});
    } catch (e) {setError(e.message);} finally {setLoading(false);}
  }
  const query=search.toLowerCase().trim();
  const rows=fixedFirst((doc?.variables ?? []).filter(v=>`${v.variable_path} ${v.unit}`.toLowerCase().includes(query)));
  return <section className="results-panel resources-panel"><header className="model_document-header"><div><h2>Results{doc ? ` · ${doc.block_id}` : ''}</h2><p>Saved numerical snapshots, separate from resource records and parameters.</p></div>{doc && <a className="model_document-download" href={url || undefined} download={`${doc.block_id}_results.json`}>Download results JSON</a>}</header>
    <section className="resources-upload" onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault();load(e.dataTransfer.files[0]);}}><b>Upload results</b><p>Drop a results JSON file here. Its model ID selects the root model; your resources file is kept separately.</p><label className="file-picker">{loading ? 'Loading…' : doc ? 'Replace results file' : 'Choose results file'}<input type="file" accept=".json,application/json" disabled={loading} onChange={e=>{load(e.target.files[0]);e.target.value='';}}/></label>{doc && <><p>{file.name}</p><button onClick={()=>{onClear();setError('');}}>Clear results</button></>}{error && <p className="upload-error" role="alert">{error}</p>}</section>
    {doc ? <><div className={`results-run status-${doc.solve.status}`}><strong>Solve status: {doc.solve.status}</strong><span>{doc.solve.termination_condition ?? 'Termination not recorded'}</span><span>{doc.solve.solver ?? 'Solver not recorded'} · {doc.mode} · time unit: {doc.time_unit}</span><span>Run {doc.run_id} · {doc.created_at}</span>{doc.solve.message && <p>{doc.solve.message}</p>}{!['optimal','feasible'].includes(doc.solve.status) && <p>This snapshot is not a converged solution.</p>}</div>
      {!sameModel(model_document,doc.model_document) && <div className="results-mismatch"><p>The saved model differs from your current selection. Diagram result previews are hidden until they match.</p><button onClick={()=>onUseModel(doc.model_document)}>Use saved model</button></div>}
      {!!analysis?.errors.length && <details className="results-mismatch" open><summary>Saved model does not match the current registry</summary>{analysis.errors.map((e,i)=><p key={i}>{e}</p>)}</details>}
      {replacements.warnings.length > 0 && <p className="results-mismatch">Load the matching resources file to resolve saved replacement record tags to variable paths.</p>}
      <label>Filter result variables<input type="search" value={search} placeholder="Variable path or unit" onChange={e=>setSearch(e.target.value)}/></label><p>{rows.length} of {doc.variables.length} variable families. Coordinates and units are saved explicitly; no conversion or propagation is applied. Fixed/free describes export-time state.</p>
      <div className="resources-table-scroll"><table className="resources-table"><thead><tr><th>Variable path</th><th>Value / coordinates</th><th>Unit</th><th>Fixed / free</th><th>Replaces input</th><th>Path in current registry</th></tr></thead><tbody>{rows.map(variable=><tr key={variable.variable_path}><td>{variable.variable_path}</td><td>{variable.entries.length===1 ? <><strong>{resultNumber(variable.entries[0])}</strong><small>{variable.dimensions.length ? variable.dimensions.map((d,i)=>`${d}=${JSON.stringify(variable.entries[0].index[i])}`).join(', ') : 'Scalar'}</small></> : <details><summary>{resultPreview(variable)}</summary><ResultValues variable={variable} mode={doc.mode} timeDimension={timeDimensionForVariable(variable,timeDomains)} timeUnit={doc.time_unit}/></details>}</td><td>{variable.unit}</td><td>{variable.entries.every(e=>e.fixed) ? 'Fixed' : variable.entries.every(e=>!e.fixed) ? 'Free' : 'Mixed — expand values'}</td><td>{replacementCell(variable,replacements.pairs,canonicalPaths,initialPaths)}</td><td>{savedPaths.has(variable.variable_path) ? 'Saved model_document' : findVariable(root,variable.variable_path,registry) ? 'Other formulation' : 'Unmatched path'}</td></tr>)}</tbody></table></div>{!rows.length && <p>No result variables match this filter.</p>}
      <details><summary>Model and parameters metadata</summary><pre>{JSON.stringify({model_document:doc.model_document,parameters:doc.parameters},null,2)}</pre></details>
    </> : <p>No results loaded. Export a ResultsDocument from Python, then upload it here. Existing diagnostic reports are a different format.</p>}
  </section>;
}
