import React, { useEffect, useState } from 'react';
import { analyzeModel, defaultModel, parseModel, replaceSelection } from './model_selection.js';
import { variableLabel } from './graph.js';

function InputGroups({ items, root }) {
  const groups = new Map();
  for (const item of items) {
    const group = [item.occurrence || root, item.struct].join(' · ');
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push(item);
  }
  return [...groups].map(([name, variables]) => <section className="required-input-group" key={name}><h4>{name}</h4>{variables.map(item => <div key={item.path} title={item.path}><span>{variableLabel(item.name, item.variable)}</span><code>{item.variable.unit ?? 'dimensionless'}</code></div>)}</section>);
}

export default function ModelPanel({ context, catalog, analysis, library, onChange, onInspect }) {
  const [fileError, setFileError] = useState('');
  const [loading, setLoading] = useState(false);
  const [downloadUrl, setDownloadUrl] = useState('');
  useEffect(() => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(catalog, null, 2) + '\n'], { type: 'application/json' }));
    setDownloadUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [catalog]);
  const root = context.definition.id;
  const byPath = new Map(analysis.occurrences.map(item => [JSON.stringify(item.path), item]));
  async function upload(file) {
    if (!file) return;
    setLoading(true); setFileError('');
    try {
      if (file.size > 5 * 1024 * 1024) throw Error('Please use a model catalog file smaller than 5 MB.');
      const candidate = parseModel(await file.text());
      const result = analyzeModel(context, candidate, library);
      if (result.errors.length) throw Error(result.errors.slice(0, 10).join('\n'));
      onChange(candidate);
    } catch (error) { setFileError(error.message); }
    finally { setLoading(false); }
  }
  function tree(path) {
    const occurrence = byPath.get(JSON.stringify(path));
    if (!occurrence) return null;
    const { context: model, selection } = occurrence;
    const prefix = path.length ? path.join('.') + '.' : '';
    const count = analysis.inputs.filter(input => input.path.startsWith(prefix)).length;
    return <details className="model_catalog-node" key={JSON.stringify(path)} open={path.length < 2}>
      <summary><strong>{path.at(-1) ?? root}</strong><span>{model.definition.id} · {count} input families in subtree</span></summary>
      <div className="model_catalog-choice"><label>Formulation for {path.join('.') || root}
        <select value={selection?.formulation ?? ''} onChange={event => onChange(replaceSelection(catalog, path, defaultModel(model, library, event.target.value)))}>
          {!model.definition.formulations[selection?.formulation] && <option value="">Choose formulation…</option>}
          {Object.keys(model.definition.formulations).map(name => <option key={name} value={name} style={{ fontWeight: name === selection?.formulation ? 700 : 400 }}>{name}</option>)}
        </select></label><button disabled={!model.definition.formulations[selection?.formulation]} onClick={() => onInspect(path)}>View diagram</button>
      </div>
      {Object.keys(selection?.subblocks ?? {}).map(alias => tree([...path, alias]))}
    </details>;
  }
  return <div className="model_catalog-panel">
    <header className="model_catalog-header"><div><h2>Model · {root}</h2><p>Choose one formulation per occurrence. Changing a formulation creates default choices for its new subtree.</p></div>
      <a className="model_catalog-download" href={!analysis.errors.length ? downloadUrl : undefined} download={`${root}_model_selection.json`} aria-disabled={!!analysis.errors.length || !downloadUrl}>Download model catalog JSON</a></header>
    <section className="model_catalog-upload" onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); if (!loading) upload(event.dataTransfer.files[0]); }}>
      <label>Drop a model catalog JSON here, or upload<input disabled={loading} type="file" accept=".json,application/json" onChange={event => { upload(event.target.files[0]); event.target.value = ''; }}/></label>
      <p>The file applies to <strong>{root}</strong>. It contains formulation choices only; select the matching root in the block library first.</p>
      {fileError && <pre role="alert">{fileError}</pre>}
    </section>
    {analysis.errors.length > 0 && <div className="model_catalog-errors" role="alert"><b>Complete or correct these choices before downloading</b>{analysis.errors.slice(0, 30).map((error, index) => <p key={index}>{error}</p>)}</div>}
    <div className="model_catalog-columns"><section><h3>Formulation choices</h3>{tree([])}</section>
      <section className="model_catalog-inputs"><h3>{analysis.inputs.length} required input families</h3>
        <p>{analysis.errors.length ? 'Partial summary until all choices are valid. ' : ''}Inputs not supplied by parent equations or connections. A block can be partially supplied, so only the remaining fields are listed. This is declaration coverage, not a solvability check.</p>
        {!analysis.inputs.length && !analysis.errors.length && <p>No external input families required.</p>}
        <InputGroups items={analysis.inputs} root={root}/>
        {analysis.initial.length > 0 && <><h3>{analysis.initial.length} dynamic initial-state families</h3><p>Separate initial profiles for derivative targets when building in dynamic mode.</p><InputGroups items={analysis.initial} root={root}/></>}
      </section></div>
  </div>;
}
