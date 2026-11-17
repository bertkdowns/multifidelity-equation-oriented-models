import React, { useEffect, useState } from 'react';
import { parseFeeds, updateFeed } from './feeds.js';

export default function FeedsPanel({ root, file, onChange, onClear }) {
  const document = file?.feeds ?? { feeds: [] };
  const feeds = document.feeds;
  const [selected, setSelected] = useState('');
  const current = feeds.find(p => p.name === selected) ?? feeds[0];
  const [config, setConfig] = useState('');
  const [error, setError] = useState(''), [message, setMessage] = useState('');
  const [url, setUrl] = useState('');
  useEffect(() => {
    setConfig(JSON.stringify(current?.config ?? {}, null, 2));
  }, [current]);
  useEffect(() => {
    const next = URL.createObjectURL(new Blob([JSON.stringify(document, null, 2) + '\n'], { type: 'application/json' }));
    setUrl(next); return () => URL.revokeObjectURL(next);
  }, [file]);
  async function load(upload) {
    if (!upload) return;
    try {
      if (upload.size > 20 * 1024 * 1024) throw Error('Please use a feed document smaller than 20 MB.');
      const feeds = parseFeeds(await upload.text());
      onChange({ name: upload.name, feeds }); setSelected(''); setError(''); setMessage('');
    } catch (error) { setError(error.message); }
  }
  function save(event) {
    event.preventDefault();
    try {
      const next = updateFeed(document, current.name, JSON.parse(config));
      onChange({ name: file.name, feeds: next });
      setError(''); setMessage('Saved feed declaration. Download the document to use it in Python.');
    } catch (error) { setError(error.message); setMessage(''); }
  }
  return <section className="resources-panel feeds-panel">
    <header className="model_document-header"><div><h2>Feeds · {root}</h2><p>Configured instances of feed plugins. No external data is fetched in this viewer.</p></div>
      <a className="model_document-download" href={url || undefined} download={`${root}_feeds.json`}>Download feeds JSON</a></header>
    <section className="resources-upload" onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); load(e.dataTransfer.files[0]); }}>
      <b>Upload feed document</b><p>Load a FeedDocument JSON file here. Connector code and credentials stay in Python.</p>
      <label className="file-picker">Choose feeds file<input type="file" accept=".json,application/json" onChange={e => { load(e.target.files[0]); e.target.value = ''; }}/></label>
      {file && <><p>{file.name}</p><button onClick={() => { onClear(); setError(''); setMessage(''); }}>Clear feeds</button></>}
    </section>
    {error && <p className="upload-error" role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    {feeds.length ? <>
      <h3>Configured feeds</h3><div className="resources-table-scroll"><table className="resources-table"><thead><tr><th>Feed</th><th>Provider type</th></tr></thead><tbody>{feeds.map(feed => <tr key={feed.name} className={feed === current ? 'feed-selected' : ''}><td><button aria-pressed={feed === current} onClick={() => { setSelected(feed.name); setError(''); setMessage(''); }}>{feed.name}</button></td><td>{feed.provider_type}</td></tr>)}</tbody></table></div>
      {current && <div className="feed-editor-columns"><section><h3>Plugin · {current.provider_type}</h3><p>Python resolves this plugin name through FeedRegistry, validates its configuration, then constructs a feed instance. get_tags() discovers resource tags at runtime; tags are not stored in this document.</p></section>
        <section className="resources-add"><h3>Edit {current.name}</h3><form onSubmit={save}>
          <label>Configuration (JSON)<textarea rows={12} value={config} onChange={e => setConfig(e.target.value)}/></label>
          <p>The viewer checks JSON. Python validates type-specific settings. Tags are discovered when the configured plugin runs in Python.</p>
          <button type="submit">Save declaration</button>
        </form></section></div>}
    </> : <p>No feeds loaded. Register plugin types in Python and provide their configuration in a feed document, or open a workspace that includes one.</p>}
    <p>Changes are saved in this browser. Download the JSON or save a workspace for a portable copy.</p>
  </section>;
}
