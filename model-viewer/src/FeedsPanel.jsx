import React, { useEffect, useState } from 'react';
import { parseFeeds, updateFeed } from './feeds.js';

export default function FeedsPanel({ root, file, resources, onChange, onClear }) {
  const feeds = file?.feeds ?? [];
  const [selected, setSelected] = useState('');
  const current = feeds.find(p => p.name === selected) ?? feeds[0];
  const [config, setConfig] = useState('');
  const [error, setError] = useState(''), [message, setMessage] = useState('');
  const [url, setUrl] = useState('');
  useEffect(() => {
    setConfig(JSON.stringify(current?.config ?? {}, null, 2));
  }, [current]);
  useEffect(() => {
    const next = URL.createObjectURL(new Blob([JSON.stringify(feeds, null, 2) + '\n'], { type: 'application/json' }));
    setUrl(next); return () => URL.revokeObjectURL(next);
  }, [file]);
  async function load(upload) {
    if (!upload) return;
    try {
      if (upload.size > 20 * 1024 * 1024) throw Error('Please use a feed catalogue smaller than 20 MB.');
      const feeds = parseFeeds(await upload.text());
      onChange({ name: upload.name, feeds }); setSelected(''); setError(''); setMessage('');
    } catch (error) { setError(error.message); }
  }
  function save(event) {
    event.preventDefault();
    try {
      const next = updateFeed(feeds, current.name, JSON.parse(config));
      onChange({ name: file.name, feeds: next });
      setError(''); setMessage('Saved feed declaration. Download the catalogue to use it in Python.');
    } catch (error) { setError(error.message); setMessage(''); }
  }
  const records = new Map((resources ?? []).map(record => [record.tag, record]));
  return <section className="resources-panel feeds-panel">
    <header className="model_catalog-header"><div><h2>Feeds · {root}</h2><p>Registered Python inputs and the resource record tags they supply. No external data is fetched in this viewer.</p></div>
      <a className="model_catalog-download" href={url || undefined} download={`${root}_feeds.json`}>Download feeds JSON</a></header>
    <section className="resources-upload" onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); load(e.dataTransfer.files[0]); }}>
      <b>Upload feed catalogue</b><p>Export data.describe() from Python, then load its JSON here. Connector code and credentials stay in Python.</p>
      <label className="file-picker">Choose feeds file<input type="file" accept=".json,application/json" onChange={e => { load(e.target.files[0]); e.target.value = ''; }}/></label>
      {file && <><p>{file.name}</p><button onClick={() => { onClear(); setError(''); setMessage(''); }}>Clear feeds</button></>}
    </section>
    {error && <p className="upload-error" role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    {feeds.length ? <>
      <h3>Registered feeds</h3><div className="resources-table-scroll"><table className="resources-table"><thead><tr><th>Feed</th><th>Provider type</th><th>Advertised tags (snapshot)</th></tr></thead><tbody>{feeds.map(feed => <tr key={feed.name} className={feed === current ? 'feed-selected' : ''}><td><button aria-pressed={feed === current} onClick={() => { setSelected(feed.name); setError(''); setMessage(''); }}>{feed.name}</button></td><td>{feed.provider_type}</td><td>{feed.tags.join(', ') || 'No tags reported'}</td></tr>)}</tbody></table></div>
      {current && <div className="feed-editor-columns"><section><h3>{current.name} · Supplied records</h3><div className="resources-table-scroll"><table className="resources-table"><thead><tr><th>Record tag</th><th>Resource type</th><th>Variable path</th><th>Unit</th></tr></thead><tbody>{current.tags.map(tag => <tr key={tag}><td>{tag}</td><td>{records.get(tag)?.resource_type ?? 'Record not loaded'}</td><td>{records.get(tag)?.variable_path ?? '—'}</td><td>{records.get(tag)?.unit ?? '—'}</td></tr>)}</tbody></table></div><p>get_tags() discovers available tags; read(tags) returns their values. Static records need no feed. Missing records are shown so the catalogue can be inspected before loading resources.</p></section>
        <section className="resources-add"><h3>Edit {current.name}</h3><form onSubmit={save}>
          <label>Configuration (JSON)<textarea rows={12} value={config} onChange={e => setConfig(e.target.value)}/></label>
          <p>The viewer checks JSON. Python validates type-specific settings. Tags are the last exported get_tags() result; reload a catalogue from Python after configuration changes to refresh them.</p>
          <button type="submit">Save declaration</button>
        </form></section></div>}
    </> : <p>No feeds loaded. Register feeds in Python and export their catalogue, or open a workspace that includes one.</p>}
    <p>Changes are saved in this browser. Download the JSON or save a workspace for a portable copy.</p>
  </section>;
}
