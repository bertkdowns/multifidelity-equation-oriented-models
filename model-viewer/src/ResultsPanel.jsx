import React, {useEffect,useMemo,useState} from 'react';
import TimeSeriesChart from './TimeSeriesChart.jsx';
import {timeDomainsByOccurrence, timeDimensionForVariable} from './time-series.js';
import {analyzeImplementation} from './implementation.js';
import {findVariable} from './information.js';
import {parseResults,resultNumber,resultPreview,sameImplementation,fixedFirst} from './results.js';

export function ResultValues({variable,mode,timeDimension,timeUnit}) {
  return <div className="result-values"><p><code>{variable.variable_path}</code> · {variable.unit}</p>{mode === 'dynamic' && timeDimension && <TimeSeriesChart variable={variable} timeDimension={timeDimension} timeUnit={timeUnit}/>}<table className="information-table"><thead><tr><th>Coordinates {variable.dimensions.length ? `(${variable.dimensions.join(', ')})` : '(scalar)'}</th><th>Value</th><th>State at export</th></tr></thead><tbody>{fixedFirst(variable.entries).map(entry=><tr key={JSON.stringify(entry.index)}><td>{JSON.stringify(entry.index)}</td><td>{resultNumber(entry)}</td><td>{entry.fixed ? 'Fixed' : 'Free'}</td></tr>)}</tbody></table></div>;
}
export default function ResultsPanel({root,file,implementation,library,onChange,onClear,onUseImplementation}) {
  const [error,setError]=useState(''),[loading,setLoading]=useState(false),[search,setSearch]=useState(''),[url,setUrl]=useState('');
  const doc=file?.document;
  const analysis=useMemo(()=>doc ? analyzeImplementation(root,doc.implementation,library) : null,[root,doc,library]);
  const timeDomains=useMemo(()=>timeDomainsByOccurrence(analysis),[analysis]);
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
      const document=parseResults(await upload.text());
      if (!library[document.model_id]) throw Error(`Model ${document.model_id} is not in this library.`);
      onChange({name:upload.name,document});
    } catch (e) {setError(e.message);} finally {setLoading(false);}
  }
  const query=search.toLowerCase().trim();
  const rows=fixedFirst((doc?.variables ?? []).filter(v=>`${v.variable_path} ${v.unit}`.toLowerCase().includes(query)));
  return <section className="results-panel information-panel"><header className="implementation-header"><div><h2>Results{doc ? ` · ${doc.model_id}` : ''}</h2><p>Saved numerical snapshots, separate from information records and specifications.</p></div>{doc && <a className="implementation-download" href={url || undefined} download={`${doc.model_id}_results.json`}>Download results JSON</a>}</header>
    <section className="information-upload" onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault();load(e.dataTransfer.files[0]);}}><b>Upload results</b><p>Drop a results JSON file here. Its model ID selects the root model; your information file is kept separately.</p><label className="file-picker">{loading ? 'Loading…' : doc ? 'Replace results file' : 'Choose results file'}<input type="file" accept=".json,application/json" disabled={loading} onChange={e=>{load(e.target.files[0]);e.target.value='';}}/></label>{doc && <><p>{file.name}</p><button onClick={()=>{onClear();setError('');}}>Clear results</button></>}{error && <p className="upload-error" role="alert">{error}</p>}</section>
    {doc ? <><div className={`results-run status-${doc.solve.status}`}><strong>Solve status: {doc.solve.status}</strong><span>{doc.solve.termination_condition ?? 'Termination not recorded'}</span><span>{doc.solve.solver ?? 'Solver not recorded'} · {doc.mode} · time unit: {doc.time_unit}</span><span>Run {doc.run_id} · {doc.created_at}</span>{doc.solve.message && <p>{doc.solve.message}</p>}{!['optimal','feasible'].includes(doc.solve.status) && <p>This snapshot is not a converged solution.</p>}</div>
      {!sameImplementation(implementation,doc.implementation) && <div className="results-mismatch"><p>The saved implementation differs from your current selection. Diagram result previews are hidden until they match.</p><button onClick={()=>onUseImplementation(doc.implementation)}>Use saved implementation</button></div>}
      {!!analysis?.errors.length && <details className="results-mismatch" open><summary>Saved implementation does not match the current library</summary>{analysis.errors.map((e,i)=><p key={i}>{e}</p>)}</details>}
      <label>Filter result variables<input type="search" value={search} placeholder="Variable path or unit" onChange={e=>setSearch(e.target.value)}/></label><p>{rows.length} of {doc.variables.length} variable families. Coordinates and units are saved explicitly; no conversion or propagation is applied. Fixed/free describes export-time state.</p>
      <div className="information-table-scroll"><table className="information-table"><thead><tr><th>Variable path</th><th>Value / coordinates</th><th>Unit</th><th>Fixed / free</th><th>Path in current library</th></tr></thead><tbody>{rows.map(variable=><tr key={variable.variable_path}><td>{variable.variable_path}</td><td>{variable.entries.length===1 ? <><strong>{resultNumber(variable.entries[0])}</strong><small>{variable.dimensions.length ? variable.dimensions.map((d,i)=>`${d}=${JSON.stringify(variable.entries[0].index[i])}`).join(', ') : 'Scalar'}</small></> : <details><summary>{resultPreview(variable)}</summary><ResultValues variable={variable} mode={doc.mode} timeDimension={timeDimensionForVariable(variable,timeDomains)} timeUnit={doc.time_unit}/></details>}</td><td>{variable.unit}</td><td>{variable.entries.every(e=>e.fixed) ? 'Fixed' : variable.entries.every(e=>!e.fixed) ? 'Free' : 'Mixed — expand values'}</td><td>{savedPaths.has(variable.variable_path) ? 'Saved implementation' : findVariable(root,variable.variable_path,library) ? 'Other relationship' : 'Unmatched path'}</td></tr>)}</tbody></table></div>{!rows.length && <p>No result variables match this filter.</p>}
      <details><summary>Implementation and specification metadata</summary><pre>{JSON.stringify({implementation:doc.implementation,specification:doc.specification},null,2)}</pre></details>
    </> : <p>No results loaded. Export a ResultsDocument from Python, then upload it here. Existing diagnostic reports are a different format.</p>}
  </section>;
}
