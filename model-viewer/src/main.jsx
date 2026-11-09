import React, { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ReactFlow, Handle, Position, Background, Controls, MiniMap, SelectionMode, useUpdateNodeInternals, applyNodeChanges } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import './style.css';
import { makeGraph, variableLabel, resolveReference } from './graph.js';
import { layoutKey, restorePositions, savePositions } from './layout-storage.js';
import { parseInformation, indexInformation, informationPreview, findVariable } from './information.js';
import { routeDetailedEdges } from './edge-routing.js';
import ImplementationPanel from './ImplementationPanel.jsx';
import InformationPanel from './InformationPanel.jsx';
import WorkspaceControls from './WorkspaceControls.jsx';
import ResultsPanel, {ResultValues} from './ResultsPanel.jsx';
import {indexResults, resultPreview, sameImplementation} from './results.js';
import { useStoredDocuments } from './use-stored-documents.js';
import { loadActiveModel, saveActiveModel } from './document-storage.js';
import { defaultImplementation, analyzeImplementation } from './implementation.js';

const documents = import.meta.glob('../../src/multifidelity/model_language/models/*.json', { eager: true, import: 'default' });
const library = Object.fromEntries(Object.values(documents).map(model => [model.id, model]));
const modelIcons = new Set(Object.keys(import.meta.glob('../public/model-icons/*.svg')).map(path => path.split('/').at(-1).replace(/\.svg$/, '')));

const ResultsContext = createContext({index:new Map(),prefix:'',inspect:()=>{},status:'not_solved'});
function ResultsValue({name,localPath}) {
  const {index,prefix,inspect,status}=useContext(ResultsContext);
  const variable=index.get([prefix,localPath].filter(Boolean).join('.'));
  return variable ? <button className="result-value nodrag nopan" title={`Saved snapshot · ${status}`} onClick={event=>{event.stopPropagation();inspect({title:name,result:{variable,status}});}}>
    {resultPreview(variable)} <code>{variable.unit}</code>
  </button> : null;
}

const InformationContext = createContext({ index: new Map(), prefix: '', inspect: () => {} });
function InformationValue({ name, variable, localPath }) {
  const { index, prefix, inspect } = useContext(InformationContext);
  const results = useContext(ResultsContext);
  const hasResult = results.index.has([results.prefix, localPath].filter(Boolean).join('.'));
  const path = [prefix, localPath].filter(Boolean).join('.');
  const records = index.get(path) ?? [];
  const record = records[0];
  return <>{record ? <button className="information-value nodrag nopan" title="Information preview — click for sources and alternatives" onClick={event => { event.stopPropagation(); inspect({ title: name, variable: { path, metadata: variable, records } }); }}>
    {informationPreview(record)} <code>{record.unit}</code>{records.length > 1 && <small> +{records.length - 1}</small>}
  </button> : !hasResult && <code>{variable.unit ?? 'dimensionless'}</code>}<ResultsValue name={name} localPath={localPath}/></>;
}
function InformationUpload({ file, root, onLoad, onClear }) {
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  async function load(upload) {
    if (!upload) return;
    setError(''); setLoading(true);
    try {
      if (upload.size > 10 * 1024 * 1024) throw Error('Please use a file smaller than 10 MB.');
      onLoad({ name: upload.name, records: parseInformation(await upload.text()) });
    } catch (error) { setError(error.message); }
    finally { setLoading(false); }
  }
  return <section className="information-upload" onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); if (!loading) load(event.dataTransfer.files[0]); }}>
    <b>Information</b><p>Drop information.json here, or choose a file. Paths are relative to <strong>{root}</strong>.</p>
    <label className="file-picker">{loading ? 'Loading…' : file ? 'Replace file' : 'Choose file'}<input type="file" accept=".json,application/json" disabled={loading} onChange={event => { load(event.target.files[0]); event.target.value = ''; }}/></label>
    {file && <><p>{file.name} · {file.records.length} records</p><button onClick={() => { onClear(); setError(''); }}>Clear</button></>}
    {error && <p role="alert" className="upload-error">{error}</p>}
    <p>Information previews only; no calculations or specifications are applied.</p>
  </section>;
}
function VariableInformation({ variable }) {
  return <div className="variable-information"><code>{variable.path}</code><p>Model unit: {variable.metadata.unit ?? 'dimensionless'}</p>
    {variable.metadata.dimensions?.length > 0 && <p>Dimensions: {variable.metadata.dimensions.join(', ')}</p>}
    <p>Records ordered by trust rank then ID. The first record is the display preview.</p>
    {variable.records.map((record, index) => <details key={record.id} open={index === 0}><summary>{informationPreview(record)} {record.unit} · trust {record.trust_rank}</summary><p>{record.information_type} · {record.tag}</p><p>Standard deviation: {record.standard_deviation == null ? 'unknown' : `${record.standard_deviation} ${record.unit}`}</p><pre>{JSON.stringify(record, null, 2)}</pre></details>)}
  </div>;
}
function Port({ id }) {
  return <><Handle type="target" position={Position.Left} id={`${id}:in`} isConnectable={false}/><Handle type="source" position={Position.Right} id={`${id}:out`} isConnectable={false}/><Handle type="source" position={Position.Left} id={`${id}:out-left`} isConnectable={false}/><Handle type="target" position={Position.Right} id={`${id}:in-right`} isConnectable={false}/></>;
}
function Entity({ id, data, selected }) {
  const [structsCollapsed, setStructsCollapsed] = useState(false);
  const [collapsedRows, setCollapsedRows] = useState({});
  const flipped = data.flipped ?? false;
  const rotation = data.rotation ?? 0;
  const setFlipped = update => data.setOrientation(id, { flipped: update(flipped), rotation });
  const setRotation = update => data.setOrientation(id, { flipped, rotation: update(rotation) });
  const updateNodeInternals = useUpdateNodeInternals();
  useEffect(() => {
    const frame = requestAnimationFrame(() => updateNodeInternals(id));
    return () => cancelAnimationFrame(frame);
  }, [id, structsCollapsed, collapsedRows, data.summary, flipped, rotation, updateNodeInternals]);
  const hiddenPorts = row => <><Port id={row.name}/>{Object.keys(row.variables).map(name => <Port key={name} id={`${row.name}.${name}`}/>)}</>;
  return <article className={`entity ${data.kind} ${data.summary ? 'summary' : ''} ${selected ? 'selected' : ''}`}>
    {data.summary && data.kind === 'model' && selected && <button className="flip-model nodrag nopan" title="Flip connection sides" aria-label="Flip connection sides" aria-pressed={flipped} onClick={event => { event.stopPropagation(); setFlipped(value => !value); }}>⇄</button>}
    {data.summary && data.kind === 'model' && selected && <button className="flip-model rotate-model nodrag nopan" title="Rotate 90° clockwise" aria-label="Rotate 90 degrees clockwise" onClick={event => { event.stopPropagation(); setRotation(value => (value + 1) % 4); }}>↻</button>}
    <header>
      {data.kind !== 'model' && <small>{data.kind === 'constraint' ? (data.equation?.derivative ? 'DERIVATIVE' : 'CONSTRAINT') : `${data.kind.toUpperCase()} STRUCT`}</small>}
      <div className="entity-heading">
        {data.kind === 'model' && modelIcons.has(data.child?.definition.id) && <img className="model-icon" style={data.summary ? { transform: `rotate(${rotation * 90}deg)` } : undefined} src={`${import.meta.env.BASE_URL}model-icons/${data.child.definition.id}.svg`} alt="" draggable={false}/>}
        <div><strong>{data.title}</strong>{data.subtitle && <span>{data.subtitle}</span>}</div>
      </div>
    </header>
    {data.summary && data.summaryPorts.map(port => {
      const sides = [Position.Right, Position.Bottom, Position.Left, Position.Top];
      const base = (port.type === 'source') !== (data.kind === 'model' && flipped) ? 0 : 2;
      const side = sides[(base + (data.kind === 'model' ? rotation : 0)) % 4];
      const horizontal = side === Position.Top || side === Position.Bottom;
      // Rotate the attachment coordinate as well as its side. Clockwise rotation
      // maps (x, y) to (1 - y, x), so quarter/half turns reverse this coordinate.
      const reverse = data.kind === 'model' && (rotation === 1 || rotation === 2);
      const offset = reverse ? `${100 - parseFloat(port.top)}%` : port.top;
      return <Handle key={port.id} id={port.id} type={port.type} position={side} style={horizontal ? { left: offset } : { top: offset }} isConnectable={false}/>;
    })}
    {!data.summary && data.kind === 'model' && data.rows.length > 0 && <div className="struct-list-toggle">
      <button className="nodrag nopan" aria-expanded={!structsCollapsed} onClick={event => { event.stopPropagation(); setStructsCollapsed(!structsCollapsed); }}>{structsCollapsed ? '▸' : '▾'} Structs <span>{data.rows.length}</span></button>
      {structsCollapsed && data.rows.map(row => <React.Fragment key={row.name}>{hiddenPorts(row)}</React.Fragment>)}
    </div>}
    {data.equation ? !data.summary && <div className="equation"><Port id="equation"/><code>{data.equation.lhs} = {data.equation.rhs}</code><small>Determines {data.equation.determines}</small>{Object.keys(data.equation.for_each ?? {}).length > 0 && <small>For each {Object.entries(data.equation.for_each).map(([index, domain]) => `${index} ∈ ${domain}`).join(', ')}</small>}</div> : !data.summary && !structsCollapsed && data.rows.map(row => <section key={row.name}>
      <div className="struct">
        {collapsedRows[row.name] ? hiddenPorts(row) : <Port id={row.name}/>}
        <button className="nodrag nopan" aria-expanded={!collapsedRows[row.name]} onClick={event => { event.stopPropagation(); setCollapsedRows(previous => ({ ...previous, [row.name]: !previous[row.name] })); }}>{collapsedRows[row.name] ? '▸' : '▾'} {row.name} <span>({Object.keys(row.variables).length})</span></button><small>{row.direction}</small>
      </div>
      {!collapsedRows[row.name] && Object.entries(row.variables).map(([name, variable]) => <div className="variable" key={name} title={JSON.stringify(variable)}><Port id={`${row.name}.${name}`}/><span>{variableLabel(name, variable)}</span><InformationValue name={name} variable={variable} localPath={`${data.kind === 'model' ? `${data.title}.` : ''}${row.name}.${name}`}/></div>)}
    </section>)}
  </article>;
}
const nodeTypes = { entity: Entity };
function SavedLayoutFlow({ graph, storageKey, children, ...props }) {
  const [nodes, setNodes] = useState(() => restorePositions(graph.nodes, storageKey));
  function setOrientation(id, orientation) {
    setNodes(previous => {
      const next = previous.map(node => node.id === id ? { ...node, data: { ...node.data, ...orientation } } : node);
      savePositions(next, storageKey);
      return next;
    });
  }
  function onNodesChange(changes) {
    setNodes(previous => {
      const next = applyNodeChanges(changes, previous);
      if (changes.some(change => change.type === 'position')) savePositions(next, storageKey);
      return next;
    });
  }
  const edges = useMemo(() => routeDetailedEdges(nodes, graph.edges), [nodes, graph.edges]);
  return <ReactFlow {...props} nodes={nodes.map(node => ({ ...node, data: { ...node.data, setOrientation } }))} onNodesChange={onNodesChange} edges={edges}>{children}</ReactFlow>;
}
function App() {
  const [trail, setTrail] = useState(() => {
    const root = loadActiveModel(library, 'steam_generating_heat_pump_system');
    return [{ definition: library[root], bindings: {}, alias: root }];
  });
  const current = trail.at(-1);
  const [choices, setChoices] = useState({});
  const [view, setView] = useState('detailed');
  const path = trail.map(item => item.alias).join('/');
  const [mode, setMode] = useState('diagram');
  const [implementations, setImplementations, implementationStorageErrors] = useStoredDocuments('implementation');
  const rootId = trail[0].definition.id;
  useEffect(() => saveActiveModel(rootId), [rootId]);
  const defaultDocument = useMemo(() => defaultImplementation(trail[0], library), [trail[0]]);
  const implementation = implementations[rootId] ?? defaultDocument;
  const implementationAnalysis = useMemo(() => analyzeImplementation(trail[0], implementation, library), [trail[0], implementation]);
  let selectedImplementation = implementation;
  for (let index = 0; index < trail.length - 1; index++) {
    const ancestorPath = trail.slice(0, index + 1).map(item => item.alias).join('/');
    if ((choices[ancestorPath] ?? selectedImplementation?.relationship) !== selectedImplementation?.relationship) { selectedImplementation = undefined; break; }
    selectedImplementation = selectedImplementation?.submodels?.[trail[index + 1].alias];
  }
  const relationship = choices[path] ?? selectedImplementation?.relationship ?? Object.keys(current.definition.relationships)[0];
  const graph = useMemo(() => makeGraph(current, relationship, library, view), [current, relationship, view]);
  const [selection, setSelection] = useState(null);
  const [informationFiles, setInformationFiles, informationStorageErrors] = useStoredDocuments('information');
  const informationFile = informationFiles[rootId];
  const [resultFiles,setResultFiles,resultStorageErrors]=useStoredDocuments('results');
  const resultFile=resultFiles[rootId];
  const resultIndex=useMemo(()=>indexResults(resultFile?.document),[resultFile]);
  const showResults=resultFile && sameImplementation(implementation,resultFile.document.implementation) && selectedImplementation?.relationship===relationship && !implementationAnalysis.errors.length;
  const resultsContext={index:showResults ? resultIndex : new Map(),prefix:trail.slice(1).map(item=>item.alias).join('.'),inspect:setSelection,status:resultFile?.document.solve.status};
  function openWorkspace(workspace, filename) {
    const root = workspace.results.model_id;
    setImplementations(previous => ({ ...previous, [root]: workspace.implementation }));
    setInformationFiles(previous => ({ ...previous, [root]: { name: `${filename} · information`, records: workspace.information } }));
    setResultFiles(previous => ({ ...previous, [root]: { name: `${filename} · results`, document: workspace.results } }));
    setTrail([{ definition: library[root], bindings: {}, alias: root }]);
    setChoices({}); setSelection(null); setMode('diagram');
  }
  function loadResults(file) {
    setResultFiles(previous=>({...previous,[file.document.model_id]:file}));
    if (file.document.model_id!==rootId) openRoot(file.document.model_id);
    setSelection(null);
  }

  const informationIndex = useMemo(() => indexInformation(informationFile?.records ?? []), [informationFile]);
  const unmatched = useMemo(() => [...informationIndex.keys()].filter(path => !findVariable(trail[0], path, library)), [informationIndex, trail[0]]);
  const informationContext = { index: informationIndex, prefix: trail.slice(1).map(item => item.alias).join('.'), inspect: setSelection };
  function setInformation(file) { setInformationFiles(previous => ({ ...previous, [rootId]: file })); setSelection(null); }
  function explore(data) { setTrail([...trail, { ...data.child, alias: data.title }]); setSelection(null); }
  function updateImplementation(document) {
    setImplementations(previous => ({ ...previous, [rootId]: document }));
    setChoices({}); setSelection(null); setTrail([trail[0]]);
  }
  function inspectImplementation(aliases) {
    const next = [trail[0]];
    let selected = implementation;
    for (const alias of aliases) {
      const parent = next.at(-1);
      const reference = parent.definition.relationships[selected.relationship].models[alias];
      next.push({ ...resolveReference(reference, parent.bindings ?? {}, library), alias });
      selected = selected.submodels[alias];
    }
    setTrail(next); setChoices({}); setSelection(null); setMode('diagram');
  }
  function openRoot(id) { setTrail([{ definition: library[id], bindings: {}, alias: id }]); setSelection(null); }
  const sidebarRef = useRef(null);
  const focusSelection = mode === 'diagram' && view === 'summary' && !!selection;
  useEffect(() => {
    if (focusSelection) sidebarRef.current?.scrollTo({ top: 0 });
  }, [focusSelection, selection]);
  const selectionDetails = selection && <div className="details"><div className="selection-heading"><h3>{selection.title}</h3><button aria-label="Close selected item details" title="Close details" onClick={() => setSelection(null)}>×</button></div>
        {selection.child && !selection.child.unresolved && <button className="explore-button" onClick={() => explore(selection)}>Explore model →</button>}
        {Object.keys(selection.domainBindings ?? {}).length > 0 && <pre>Domain bindings: {JSON.stringify(selection.domainBindings, null, 2)}</pre>}
        {selection.result ? <><p>Saved snapshot · {selection.result.status}</p><ResultValues variable={selection.result.variable}/></> : selection.variable ? <VariableInformation variable={selection.variable}/> : selection.equation || selection.connection ? <pre>{JSON.stringify(selection.equation ?? selection.connection, null, 2)}</pre> : selection.rows.map(row => <section className="sidebar-struct" key={row.name}><h4>{row.name} <small>{row.direction}</small></h4>{Object.entries(row.variables).map(([name, variable]) => <div key={name} title={JSON.stringify(variable)}><span>{variableLabel(name, variable)}</span><InformationValue name={name} variable={variable} localPath={`${selection.kind === 'model' ? `${selection.title}.` : ''}${row.name}.${name}`}/></div>)}</section>)}
      </div>;
  return <InformationContext.Provider value={informationContext}><ResultsContext.Provider value={resultsContext}><main>
    <aside ref={sidebarRef}><div className="brand">◈ <span>MULTIFIDELITY</span></div><h1>Model explorer</h1>
      {[...implementationStorageErrors, ...informationStorageErrors, ...resultStorageErrors].map(message => <p key={message} className="upload-error" role="status">{message}</p>)}
      {focusSelection && selectionDetails}
      <details className={`sidebar-controls ${focusSelection ? 'collapsed-controls' : 'expanded-controls'}`} open={!focusSelection}>
        <summary>Model controls &amp; help</summary>
      <WorkspaceControls root={rootId} implementation={implementation} information={informationFile?.records} results={resultFile?.document} library={library} onOpen={openWorkspace}/>
      <label>Model library<select value={trail[0].definition.id} onChange={event => openRoot(event.target.value)}>{Object.keys(library).sort().map(id => <option key={id}>{id}</option>)}</select></label>
      <button className="implementation-open" onClick={() => setMode('information')}>Choose information</button>
      {informationFile && <p className="information-file-status">{informationFile.name} · {informationFile.records.length} records</p>}
      {unmatched.length > 0 && <details className="unmatched"><summary>{unmatched.length} unmatched variable paths</summary><p>These paths were not found in the available model definitions.</p>{unmatched.map(path => <div key={path}>{path}</div>)}</details>}
      {informationFile && <p>Records in other relationships appear when you explore those models. No values are propagated along connections.</p>}
      <button className="implementation-open" onClick={() => setMode('implementation')}>Choose implementation</button>
      <label>Preview relationship<select style={{ fontWeight: relationship === selectedImplementation?.relationship ? 700 : 400 }} value={relationship ?? ''} onChange={event => { setChoices({ ...choices, [path]: event.target.value }); setSelection(null); }}>{Object.keys(current.definition.relationships).map(name => <option key={name} value={name} style={{ fontWeight: name === selectedImplementation?.relationship ? 700 : 400 }}>{name}{name === selectedImplementation?.relationship ? ' (implementation)' : ''}</option>)}</select></label>
      {relationship !== selectedImplementation?.relationship && <button className="implementation-open" onClick={() => inspectImplementation([])}>View selected implementation</button>}
      <p className="description">{current.definition.description}</p>
      {Object.keys(current.definition.domains ?? {}).length > 0 && <div className="domain-info"><b>Index domains</b>{Object.entries(current.definition.domains).map(([name, domain]) => <div key={name}>{name} · {domain.kind}{current.domainBindings?.[name] && ` → parent.${current.domainBindings[name]}`}</div>)}<p>Indexed variables and equations are shown as families, without expanding time points or domain members.</p></div>}
      <div className="legend"><span>● Input struct</span><span>● Model</span><span>● Constraint</span><span>● Output struct</span></div>
      <p>Teal lines connect whole structs. Purple lines show equation references, pointing toward the variable declared by <code>determines</code>.</p>
      <p>Drag on empty space to box-select nodes, then drag a selected node to move the group. Pan with the middle or right mouse button. Ctrl/Cmd-click adds to the selection.</p>
      {graph.warnings.length > 0 && <div className="warnings">{graph.warnings.map(message => <p key={message}>{message}</p>)}</div>}
      </details>
      {!focusSelection && selectionDetails}
      <footer>Read-only · JSON definitions<br/>{Object.keys(library).length} models in library</footer>
    </aside>
    <div className="workspace"><div className="workspace-tabs" role="group" aria-label="Workspace mode"><button aria-pressed={mode === 'diagram'} onClick={() => setMode('diagram')}>Diagram</button><button aria-pressed={mode === 'implementation'} onClick={() => setMode('implementation')}>Implementation</button><button aria-pressed={mode === 'information'} onClick={() => setMode('information')}>Information</button><button aria-pressed={mode === 'results'} onClick={() => setMode('results')}>Results</button></div><nav aria-label="Model breadcrumb">{trail.map((item, index) => <React.Fragment key={index}>{index > 0 && <span>/</span>}<button onClick={() => { setTrail(trail.slice(0, index + 1)); setSelection(null); }}>{item.alias}</button></React.Fragment>)}</nav>
      {mode === 'results' ? <ResultsPanel key={rootId} root={trail[0]} file={resultFile} implementation={implementation} library={library} onChange={loadResults} onClear={()=>setResultFiles(previous=>({...previous,[rootId]:null}))} onUseImplementation={updateImplementation}/> : mode === 'information' ? <InformationPanel key={rootId} root={trail[0]} file={informationFile} analysis={implementationAnalysis} library={library} onChange={setInformation} uploadControl={<InformationUpload key={rootId} file={informationFile} root={rootId} onLoad={setInformation} onClear={() => setInformation(null)}/>}/> : mode === 'implementation' ? <ImplementationPanel key={rootId} context={trail[0]} document={implementation} analysis={implementationAnalysis} library={library} onChange={updateImplementation} onInspect={inspectImplementation}/> : <>
      <div className="canvas-title"><div><small>RELATIONSHIP</small><h2>{relationship ?? 'No relationships'}</h2></div><div className="view-toggle" role="group" aria-label="Diagram view">{['summary', 'detailed'].map(mode => <button key={mode} aria-pressed={view === mode} onClick={() => setView(mode)}>{mode === 'summary' ? 'Summary' : 'Detailed'}</button>)}</div><span>{graph.nodes.length} nodes · {graph.edges.length} links</span></div>
      <div className="canvas"><SavedLayoutFlow key={`${path}:${relationship}:${view}`} graph={graph} storageKey={layoutKey(current.definition.id, relationship, view)} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.15 }} minZoom={0.05} maxZoom={2} nodesConnectable={false} deleteKeyCode={null}
        selectionOnDrag selectionMode={SelectionMode.Partial} panOnDrag={[1, 2]} multiSelectionKeyCode={['Control', 'Meta']}
        onPaneClick={() => setSelection(null)}
        zoomOnDoubleClick={false}
        onNodeDoubleClick={(_, node) => { if (view === 'summary' && node.data.child && !node.data.child.unresolved) explore(node.data); }}
        onNodeClick={(event, node) => { if (event.ctrlKey || event.metaKey || event.shiftKey) return; if (view === 'detailed' && node.data.child && !node.data.child.unresolved) explore(node.data); else setSelection(node.data); }}
        onEdgeClick={(_, edge) => setSelection({ title: edge.label, connection: { from: (edge.data.sourcePort ?? edge.sourceHandle)?.replace(/:out$/, ''), to: (edge.data.targetPort ?? edge.targetHandle)?.replace(/:in$/, ''), kind: edge.data.kind } })}>
        <Background color="#d8dee5" gap={22}/><Controls/><MiniMap pannable zoomable nodeColor={node => ({ model: '#608ce6', constraint: '#ac8fd2', input: '#53b5ac', output: '#e4ae62' })[node.data.kind]}/>
      </SavedLayoutFlow></div></>}
    </div>
  </main></ResultsContext.Provider></InformationContext.Provider>;
}
createRoot(document.getElementById('root')).render(<App/>);
