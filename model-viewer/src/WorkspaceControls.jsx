import React, { useEffect, useMemo, useState } from 'react';
import { parseWorkspace } from './workspace.js';

export default function WorkspaceControls({ root, implementation, information, results, library, onOpen }) {
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);
  const [url, setUrl] = useState('');
  const bundle = useMemo(() => {
    if (!results) return { problem: 'Load results to save a workspace.' };
    try {
      if (results.model_id !== root) throw Error('Results must belong to this root model.');
      return { document: parseWorkspace(JSON.stringify({ implementation, information: information ?? [], results })) };
    } catch (error) { return { problem: error.message }; }
  }, [root, implementation, information, results]);
  useEffect(() => {
    if (!bundle.document) { setUrl(''); return; }
    const next = URL.createObjectURL(new Blob([JSON.stringify(bundle.document, null, 2) + '\n'], { type: 'application/json' }));
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [bundle]);
  async function open(file) {
    if (!file || loading) return;
    setLoading(true); setError(''); setMessage('');
    try {
      if (file.size > 40 * 1024 * 1024) throw Error('Please use a workspace smaller than 40 MB.');
      const workspace = parseWorkspace(await file.text());
      if (!Object.hasOwn(library, workspace.results.model_id)) throw Error(`Model ${workspace.results.model_id} is not in the library.`);
      onOpen(workspace, file.name);
      setMessage(`Opened ${file.name}`);
    } catch (error) { setError(error.message); }
    finally { setLoading(false); }
  }
  return <section className="workspace-files" aria-label="Workspace files" onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); open(event.dataTransfer.files[0]); }}>
    <div className="workspace-file-actions"><label className="workspace-open">{loading ? 'Opening…' : 'Open workspace'}<input type="file" accept=".json,application/json" disabled={loading} onChange={event => { open(event.target.files[0]); event.target.value = ''; }}/></label>
      <a href={!bundle.problem && url ? url : undefined} aria-disabled={!!bundle.problem || !url} download={`${root}_workspace.json`}>Save workspace</a></div>
    <p>{bundle.problem ?? 'Implementation, information and results in one file.'}</p>
    {error && <p className="upload-error" role="alert">{error}</p>}{message && <p role="status">{message}</p>}
  </section>;
}
