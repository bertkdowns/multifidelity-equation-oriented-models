import React, { useEffect, useMemo, useState } from 'react';
import { appendInformation, findVariable, indexInformation, informationPreview, informationTypes, valueShape } from './information.js';

const emptyDraft = { id: '', tag: '', variable_path: '', information_type: 'assumption', type: 'constant', value: '', unit: '', standard_deviation: '', trust_rank: '5' };

export default function InformationPanel({ root, file, analysis, library, onChange, uploadControl }) {
  const records = file?.records ?? [];
  const [draft, setDraft] = useState(emptyDraft);
  const [search, setSearch] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [downloadUrl, setDownloadUrl] = useState('');
  const index = useMemo(() => indexInformation(records), [records]);
  const variables = useMemo(() => {
    const result = new Map();
    for (const occurrence of analysis.occurrences)
      for (const [struct, definition] of Object.entries(occurrence.context.definition.structs))
        for (const [name, variable] of Object.entries(definition.variables)) result.set([...occurrence.path, struct, name].join('.'), variable);
    return result;
  }, [analysis]);
  useEffect(() => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(records, null, 2) + '\n'], { type: 'application/json' }));
    setDownloadUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  const matchedVariable = draft.variable_path ? findVariable(root, draft.variable_path, library) : undefined;
  function field(name, value) { setDraft(previous => ({ ...previous, [name]: value })); setError(''); setMessage(''); }
  function setPath(path) {
    const variable = findVariable(root, path, library);
    setDraft(previous => ({ ...previous, variable_path: path, unit: variable?.unit ?? previous.unit }));
    setError(''); setMessage('');
  }
  function add(event) {
    event.preventDefault(); setError(''); setMessage('');
    try {
      const next = appendInformation(records, draft);
      onChange({ name: file?.name ?? `${root.definition.id}_information.json`, records: next });
      setMessage(`Added ${draft.id.trim()}. The diagram preview updates automatically.`);
      setDraft({ ...emptyDraft, variable_path: draft.variable_path, unit: draft.unit });
    } catch (error) { setError(error.message); }
  }
  const query = search.trim().toLowerCase();
  const visible = records.filter(record => [record.id, record.tag, record.variable_path, record.information_type, record.unit].some(value => value.toLowerCase().includes(query)));
  return <section className="information-panel">
    <header className="implementation-header"><div><h2>Information · {root.definition.id}</h2><p>{records.length} records · {index.size} variable paths. Records are information previews, not computed results or selected specifications.</p></div>
      <a className="implementation-download" href={downloadUrl || undefined} download={`${root.definition.id}_information.json`}>Download information JSON</a></header>
    {uploadControl}
    <div className="information-editor-columns"><section className="information-records">
      <label>Filter records<input type="search" value={search} placeholder="Variable path, ID, tag, source or unit" onChange={event => setSearch(event.target.value)}/></label>
      <p>{visible.length} of {records.length} records. Preview marks the highest-trust candidate for each path; all alternatives are retained.</p>
      <div className="information-table-scroll"><table className="information-table"><thead><tr><th>ID / tag</th><th>Variable path</th><th>Source</th><th>Value</th><th>Unit</th><th>Std. deviation</th><th>Trust</th><th>Display / path</th></tr></thead>
        <tbody>{visible.map(record => {
          const matched = variables.has(record.variable_path) ? 'In implementation' : findVariable(root, record.variable_path, library) ? 'Other relationship' : 'Unmatched path';
          return <tr key={record.id}><td><strong>{record.id}</strong><small>{record.tag}</small></td><td>{record.variable_path}</td><td>{record.information_type}</td><td><small>{record.type}</small>{record.type === 'series' ? <details><summary>{informationPreview(record)}</summary><pre>{JSON.stringify(record.value, null, 2)}</pre><small>Shape: {valueShape(record.value).join(' × ')}</small></details> : record.value.toString()}</td><td>{record.unit}</td><td>{record.standard_deviation ?? 'Unknown'}</td><td>{record.trust_rank}</td><td>{index.get(record.variable_path)[0].id === record.id && <b className="preview-badge">Preview</b>}<small>{matched}</small></td></tr>;
        })}</tbody></table></div>
      {!visible.length && <p>{records.length ? 'No records match this filter.' : 'Upload an information file or add your first record.'}</p>}
    </section><section className="information-add"><h3>Add information record</h3>
      <form onSubmit={add}>
        <label>Record ID<input required value={draft.id} onChange={event => field('id', event.target.value)}/></label>
        <label>Tag<input required value={draft.tag} onChange={event => field('tag', event.target.value)}/></label>
        <label>Variable path<input required list="information-variable-paths" value={draft.variable_path} onChange={event => setPath(event.target.value)} placeholder="child.struct.variable"/></label>
        <datalist id="information-variable-paths">{[...variables.keys()].sort().map(path => <option key={path} value={path}/>)}</datalist>
        {draft.variable_path && <p>{matchedVariable ? `Model unit: ${matchedVariable.unit ?? 'dimensionless'}${matchedVariable.dimensions?.length ? ` · Dimensions: ${matchedVariable.dimensions.join(', ')}` : ''}` : 'Path is not in the current library. You can keep it as an unmatched record.'}</p>}
        <label>Information source<select value={draft.information_type} onChange={event => field('information_type', event.target.value)}>{informationTypes.map(type => <option key={type} value={type}>{type.replaceAll('_', ' ')}</option>)}</select></label>
        <label>Value type<select value={draft.type} onChange={event => field('type', event.target.value)}><option value="constant">Constant</option><option value="series">Series / numeric array</option></select></label>
        <label>{draft.type === 'series' ? 'Values (JSON array)' : 'Value (number)'}<textarea required rows={draft.type === 'series' ? 5 : 2} value={draft.value} placeholder={draft.type === 'series' ? '[1, 2, 3]' : '12.5'} onChange={event => field('value', event.target.value)}/></label>
        <label>Unit<input required value={draft.unit} onChange={event => field('unit', event.target.value)}/></label>
        <label>Standard deviation (optional)<input type="number" min="0" step="any" value={draft.standard_deviation} onChange={event => field('standard_deviation', event.target.value)}/></label>
        <label>Trust rank (1–10)<input required type="number" min="1" max="10" step="1" value={draft.trust_rank} onChange={event => field('trust_rank', event.target.value)}/></label>
        <p>Series follow variable dimension order; no solver grid or unit conversion is applied. Missing uncertainty means unknown.</p>
        {error && <p className="upload-error" role="alert">{error}</p>}{message && <p role="status">{message}</p>}
        <button type="submit">Add record</button>
      </form>
    </section></div>
    <p>Changes are saved in this browser across refreshes. Download the JSON for a portable copy; the original file is never modified.</p>
  </section>;
}
