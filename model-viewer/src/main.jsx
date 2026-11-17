import React, { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ReactFlow, Panel, Handle, Position, Background, Controls, MiniMap, SelectionMode, useUpdateNodeInternals, applyNodeChanges } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import './style.css';
import { diagramColors, arrowTypes, loadArrowVisibility, saveArrowVisibility, visibleEdges } from './diagram-theme.js';
import { makeGraph, variableLabel, resolveReference } from './graph.js';
import { displayedValues, replacementPairs } from './replacement-display.js';
import { layoutKey, restorePositions, savePositions } from './layout-storage.js';
import { parseResources, indexResources, resourcePreview, findVariable } from './resources.js';
import { routeDetailedEdges, summaryPortGeometry } from './edge-routing.js';
import ModelPanel from './ModelPanel.jsx';
import ResourcesPanel from './ResourcesPanel.jsx';
import FeedsPanel from './FeedsPanel.jsx';
import WorkspaceControls from './WorkspaceControls.jsx';
import TimeSeriesChart from './TimeSeriesChart.jsx';
import { timeDomainsByOccurrence, timeDimensionForVariable } from './time-series.js';
import ResultsPanel, {ResultValues} from './ResultsPanel.jsx';
import {indexResults, resultPreview, sameModel} from './results.js';
import { useStoredCatalogs } from './use-stored-catalogs.js';
import { loadActiveBlock, saveActiveBlock } from './catalog-storage.js';
import { defaultModel, analyzeModel } from './model_selection.js';

for (const [name, color] of Object.entries(diagramColors)) document.documentElement.style.setProperty(`--diagram-${name}`, color);

const definitions = import.meta.glob('../../src/multifidelity/model_language/blocks/*.json', { eager: true, import: 'default' });
const registry = Object.fromEntries(Object.values(definitions).map(model => [model.id, model]));
const blockIcons = new Set(Object.keys(import.meta.glob('../public/block-icons/*.svg')).map(path => path.split('/').at(-1).replace(/\.svg$/, '')));

const ResultsContext = createContext({index:new Map(),prefix:'',inspect:()=>{},status:'not_solved',specifiedTags:new Set()});
function ResultsValue({name,localPath}) {
  const {index,prefix,inspect,status}=useContext(ResultsContext);
  const variable=index.get([prefix,localPath].filter(Boolean).join('.'));
  return variable ? <button className="result-value nodrag nopan" title={`Saved snapshot · ${status}`} onClick={event=>{event.stopPropagation();inspect({title:name,result:{variable,status}});}}>
    {resultPreview(variable)} <code>{variable.unit}</code>
  </button> : null;
}

function VariableTrajectory({ localPath }) {
  const results = useContext(ResultsContext);
  if (results.mode !== 'dynamic') return null;
  const variable = results.index.get([results.prefix, localPath].filter(Boolean).join('.'));
  if (!variable) return null;
  const dimension = timeDimensionForVariable(variable, results.timeDomains);
  return dimension ? <TimeSeriesChart variable={variable} timeDimension={dimension} timeUnit={results.timeUnit}/> : null;
}

const ResourceContext = createContext({ index: new Map(), prefix: '', inspect: () => {} });
function ResourceValue({ name, variable, localPath }) {
  const { index, prefix, inspect } = useContext(ResourceContext);
  const results = useContext(ResultsContext);
  const savedResult = results.index.get([results.prefix, localPath].filter(Boolean).join('.'));
  const path = [prefix, localPath].filter(Boolean).join('.');
  const records = index.get(path) ?? [];
  const {record, result} = displayedValues(records, savedResult, results.specifiedTags);
  return <>{record ? <button className="resources-value nodrag nopan" title="Resource preview — click for sources and alternatives" onClick={event => { event.stopPropagation(); inspect({ title: name, variable: { path, metadata: variable, records, selectedRecordTag: results.specifiedTags?.has(record.tag) ? record.tag : null } }); }}>
    {resourcePreview(record)} <code>{record.unit}</code>{records.length > 1 && <small> +{records.length - 1}</small>}
  </button> : !result && <code>{variable.unit ?? 'dimensionless'}</code>}{result && <ResultsValue name={name} localPath={localPath}/>}</>;
}
function ResourceUpload({ file, root, onLoad, onClear }) {
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  async function load(upload) {
    if (!upload) return;
    setError(''); setLoading(true);
    try {
      if (upload.size > 10 * 1024 * 1024) throw Error('Please use a file smaller than 10 MB.');
      onLoad({ name: upload.name, records: parseResources(await upload.text()) });
    } catch (error) { setError(error.message); }
    finally { setLoading(false); }
  }
  return <section className="resources-upload" onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); if (!loading) load(event.dataTransfer.files[0]); }}>
    <b>Resource</b><p>Drop resources.json here, or choose a file. Paths are relative to <strong>{root}</strong>.</p>
    <label className="file-picker">{loading ? 'Loading…' : file ? 'Replace file' : 'Choose file'}<input type="file" accept=".json,application/json" disabled={loading} onChange={event => { load(event.target.files[0]); event.target.value = ''; }}/></label>
    {file && <><p>{file.name} · {file.records.length} records</p><button onClick={() => { onClear(); setError(''); }}>Clear</button></>}
    {error && <p role="alert" className="upload-error">{error}</p>}
    <p>Resource previews only; no calculations or parameters are applied.</p>
  </section>;
}
function VariableResources({ variable }) {
  return <div className="variable-resources"><code>{variable.path}</code><p>Declared unit: {variable.metadata.unit ?? 'dimensionless'}</p>
    {variable.metadata.dimensions?.length > 0 && <p>Dimensions: {variable.metadata.dimensions.join(', ')}</p>}
    <p>Records ordered by trust rank then tag. {variable.selectedRecordTag ? `The parameters selects ${variable.selectedRecordTag}.` : 'The first record is the display preview.'}</p>
    {variable.records.map((record, index) => <details key={record.tag} open={variable.selectedRecordTag ? record.tag === variable.selectedRecordTag : index === 0}><summary>{resourcePreview(record)} {record.unit} · trust {record.trust_rank}</summary><p>{record.resource_type}</p><p>Standard deviation: {record.standard_deviation == null ? 'unknown' : `${record.standard_deviation} ${record.unit}`}</p><pre>{JSON.stringify(record, null, 2)}</pre></details>)}
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
  }, [id, structsCollapsed, collapsedRows, data.summary, data.replacementPorts, data.summaryPorts, flipped, rotation, updateNodeInternals]);
  const hiddenPorts = row => <><Port id={row.name}/>{Object.keys(row.variables).map(name => <Port key={name} id={`${row.name}.${name}`}/>)}</>;
  return <article className={`entity ${data.kind} ${data.summary ? 'summary' : ''} ${selected ? 'selected' : ''}`}>
    {data.summary && data.kind === 'block' && selected && <button className="flip-model nodrag nopan" title="Flip connection sides" aria-label="Flip connection sides" aria-pressed={flipped} onClick={event => { event.stopPropagation(); setFlipped(value => !value); }}>⇄</button>}
    {data.summary && data.kind === 'block' && selected && <button className="flip-model rotate-model nodrag nopan" title="Rotate 90° clockwise" aria-label="Rotate 90 degrees clockwise" onClick={event => { event.stopPropagation(); setRotation(value => (value + 1) % 4); }}>↻</button>}
    <header>
      {data.kind !== 'block' && <small>{data.kind === 'constraint' ? (data.equation?.derivative ? 'DERIVATIVE' : 'CONSTRAINT') : `${data.kind.toUpperCase()} STRUCT`}</small>}
      <div className="entity-heading">
        {data.kind === 'block' && blockIcons.has(data.child?.definition.id) && <img className="block-icon" style={data.summary ? { transform: `rotate(${rotation * 90}deg)` } : undefined} src={`${import.meta.env.BASE_URL}block-icons/${data.child.definition.id}.svg`} alt="" draggable={false}/>}
        <div><strong>{data.title}</strong>{data.subtitle && <span>{data.subtitle}</span>}</div>
      </div>
    </header>
    {data.summary && data.summaryPorts.map(port => {
      const {side, style} = summaryPortGeometry(port, {kind: data.kind, flipped, rotation});
      return <Handle key={port.id} id={port.id} type={port.type} position={side} className={port.replacement ? 'replacement-handle' : ''} style={style} isConnectable={false}/>;
    })}
    {!data.summary && data.replacementPorts?.map((port, index) => <div key={port} className="replacement-port" style={{top: `${100 * (index + 1) / (data.replacementPorts.length + 1)}%`}} title={port.slice('replacement:'.length)}><Port id={port}/></div>)}
    {!data.summary && data.kind === 'block' && data.rows.length > 0 && <div className="struct-list-toggle">
      <button className="nodrag nopan" aria-expanded={!structsCollapsed} onClick={event => { event.stopPropagation(); setStructsCollapsed(!structsCollapsed); }}>{structsCollapsed ? '▸' : '▾'} Structs <span>{data.rows.length}</span></button>
      {structsCollapsed && data.rows.map(row => <React.Fragment key={row.name}>{hiddenPorts(row)}</React.Fragment>)}
    </div>}
    {data.equation ? !data.summary && <div className="equation"><Port id="equation"/><code>{data.equation.lhs} = {data.equation.rhs}</code><small>Determines {data.equation.determines}</small>{Object.keys(data.equation.for_each ?? {}).length > 0 && <small>For each {Object.entries(data.equation.for_each).map(([index, domain]) => `${index} ∈ ${domain}`).join(', ')}</small>}</div> : !data.summary && !structsCollapsed && data.rows.map(row => <section key={row.name} data-direction={row.direction}>
      <div className="struct">
        {collapsedRows[row.name] ? hiddenPorts(row) : <Port id={row.name}/>}
        <button className="nodrag nopan" aria-expanded={!collapsedRows[row.name]} onClick={event => { event.stopPropagation(); setCollapsedRows(previous => ({ ...previous, [row.name]: !previous[row.name] })); }}>{collapsedRows[row.name] ? '▸' : '▾'} {row.name} <span>({Object.keys(row.variables).length})</span></button><small>{row.direction}</small>
      </div>
      {!collapsedRows[row.name] && Object.entries(row.variables).map(([name, variable]) => <div className="variable" key={name} title={JSON.stringify(variable)}><Port id={`${row.name}.${name}`}/><span>{variableLabel(name, variable)}</span><ResourceValue name={name} variable={variable} localPath={`${data.kind === 'block' ? `${data.title}.` : ''}${row.name}.${name}`}/></div>)}
    </section>)}
  </article>;
}
const nodeTypes = { entity: Entity };
function SavedLayoutFlow({ graph, storageKey, arrowVisibility, children, ...props }) {
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
  return <ReactFlow {...props} nodes={nodes.map(node => ({ ...node, data: { ...node.data, setOrientation } }))} onNodesChange={onNodesChange} edges={visibleEdges(edges, arrowVisibility)}>{children}</ReactFlow>;
}
function App() {
  const [trail, setTrail] = useState(() => {
    const root = loadActiveBlock(registry, 'steam_generating_heat_pump_system');
    return [{ definition: registry[root], bindings: {}, alias: root }];
  });
  const current = trail.at(-1);
  const [choices, setChoices] = useState({});
  const [view, setView] = useState('detailed');
  const [arrowVisibility, setArrowVisibility] = useState(loadArrowVisibility);
  useEffect(() => saveArrowVisibility(arrowVisibility), [arrowVisibility]);
  const path = trail.map(item => item.alias).join('/');
  const [mode, setMode] = useState('diagram');
  const [modelDocuments, setModels, model_documentStorageErrors] = useStoredCatalogs('model_document');
  const rootId = trail[0].definition.id;
  useEffect(() => saveActiveBlock(rootId), [rootId]);
  const defaultDocument = useMemo(() => defaultModel(trail[0], registry), [trail[0]]);
  const model_document = modelDocuments[rootId] ?? defaultDocument;
  const model_documentAnalysis = useMemo(() => analyzeModel(trail[0], model_document, registry), [trail[0], model_document]);
  let selectedModel = model_document;
  for (let index = 0; index < trail.length - 1; index++) {
    const ancestorPath = trail.slice(0, index + 1).map(item => item.alias).join('/');
    if ((choices[ancestorPath] ?? selectedModel?.formulation) !== selectedModel?.formulation) { selectedModel = undefined; break; }
    selectedModel = selectedModel?.subblocks?.[trail[index + 1].alias];
  }
  const formulation = choices[path] ?? selectedModel?.formulation ?? Object.keys(current.definition.formulations)[0];
  const [selection, setSelection] = useState(null);
  const [resourcesFiles, setResourcesFiles, resourcesStorageErrors] = useStoredCatalogs('resources');
  const resourcesFile = resourcesFiles[rootId];
  const [resultFiles,setResultFiles,resultStorageErrors]=useStoredCatalogs('results');
  const resultFile=resultFiles[rootId];
  const [feedFiles, setFeedFiles, feedStorageErrors] = useStoredCatalogs('feeds');
  const feedFile = feedFiles[rootId];
  const timeDomains = useMemo(() => timeDomainsByOccurrence(model_documentAnalysis), [model_documentAnalysis]);
  const resultIndex=useMemo(()=>indexResults(resultFile?.catalog),[resultFile]);
  const showResults=resultFile && sameModel(model_document,resultFile.catalog.model_document) && selectedModel?.formulation===formulation && !model_documentAnalysis.errors.length;
  const prefix = trail.slice(1).map(item=>item.alias).join('.');
  const specifiedTags = useMemo(() => new Set(showResults ? [
    ...(resultFile.catalog.parameters?.parameters ?? []),
    ...(resultFile.catalog.parameters?.initial_values ?? []),
  ] : []), [showResults, resultFile]);
  const replacements = useMemo(() => replacementPairs(showResults ? resultFile.catalog.parameters : null, resourcesFile?.records ?? []), [showResults, resultFile, resourcesFile]);
  const graph = useMemo(() => {
    const graph = makeGraph(current, formulation, registry, view, replacements.pairs, prefix);
    return {...graph, warnings: [...graph.warnings, ...replacements.warnings]};
  }, [current, formulation, view, replacements, prefix]);
  const resultsContext={index:showResults ? resultIndex : new Map(),prefix,inspect:setSelection,status:resultFile?.catalog.solve.status,specifiedTags,mode:resultFile?.catalog.mode,timeUnit:resultFile?.catalog.time_unit,timeDomains};
  function openWorkspace(workspace, filename) {
    const root = workspace.results.block_id;
    setModels(previous => ({ ...previous, [root]: workspace.model_document }));
    setResourcesFiles(previous => ({ ...previous, [root]: { name: `${filename} · resources`, records: workspace.resources } }));
    setResultFiles(previous => ({ ...previous, [root]: { name: `${filename} · results`, catalog: workspace.results } }));
    setFeedFiles(previous => ({ ...previous, [root]: workspace.feeds ? { name: `${filename} · feeds`, feeds: workspace.feeds } : null }));
    setTrail([{ definition: registry[root], bindings: {}, alias: root }]);
    setChoices({}); setSelection(null); setMode('diagram');
  }
  function loadResults(file) {
    setResultFiles(previous=>({...previous,[file.catalog.block_id]:file}));
    if (file.catalog.block_id!==rootId) openRoot(file.catalog.block_id);
    setSelection(null);
  }

  const resourcesIndex = useMemo(() => indexResources(resourcesFile?.records ?? []), [resourcesFile]);
  const unmatched = useMemo(() => [...resourcesIndex.keys()].filter(path => !findVariable(trail[0], path, registry)), [resourcesIndex, trail[0]]);
  const resourcesContext = { index: resourcesIndex, prefix: trail.slice(1).map(item => item.alias).join('.'), inspect: setSelection };
  function setResources(file) { setResourcesFiles(previous => ({ ...previous, [rootId]: file })); setSelection(null); }
  function explore(data) { setTrail([...trail, { ...data.child, alias: data.title }]); setSelection(null); }
  function updateModel(document) {
    setModels(previous => ({ ...previous, [rootId]: document }));
    setChoices({}); setSelection(null); setTrail([trail[0]]);
  }
  function inspectModel(aliases) {
    const next = [trail[0]];
    let selected = model_document;
    for (const alias of aliases) {
      const parent = next.at(-1);
      const reference = parent.definition.formulations[selected.formulation].blocks[alias];
      next.push({ ...resolveReference(reference, parent.bindings ?? {}, registry), alias });
      selected = selected.subblocks[alias];
    }
    setTrail(next); setChoices({}); setSelection(null); setMode('diagram');
  }
  function openRoot(id) { setTrail([{ definition: registry[id], bindings: {}, alias: id }]); setSelection(null); }
  const sidebarRef = useRef(null);
  const focusSelection = mode === 'diagram' && view === 'summary' && !!selection;
  useEffect(() => {
    if (focusSelection) sidebarRef.current?.scrollTo({ top: 0 });
  }, [focusSelection, selection]);
  const selectionDetails = selection && <div className="details"><div className="selection-heading"><h3>{selection.title}</h3><button aria-label="Close selected item details" title="Close details" onClick={() => setSelection(null)}>×</button></div>
        {selection.child && !selection.child.unresolved && <button className="explore-button" onClick={() => explore(selection)}>Explore model →</button>}
        {Object.keys(selection.domainBindings ?? {}).length > 0 && <pre>Domain bindings: {JSON.stringify(selection.domainBindings, null, 2)}</pre>}
        {showResults && resultFile.catalog.mode === 'dynamic' && selection.rows?.length > 0 && <p>Saved dynamic snapshot · {resultFile.catalog.solve.status} · time in {resultFile.catalog.time_unit}</p>}
        {selection.result ? <><p>Saved snapshot · {selection.result.status}</p><ResultValues variable={selection.result.variable} mode={resultFile?.catalog.mode} timeDimension={timeDimensionForVariable(selection.result.variable, timeDomains)} timeUnit={resultFile?.catalog.time_unit}/></> : selection.variable ? <VariableResources variable={selection.variable}/> : selection.equation || selection.connection ? <pre>{JSON.stringify(selection.equation ?? selection.connection, null, 2)}</pre> : selection.rows.map(row => <section className="sidebar-struct" data-direction={row.direction} key={row.name}><h4>{row.name} <small>{row.direction}</small></h4>{Object.entries(row.variables).map(([name, variable]) => <div className="sidebar-variable" key={name}><div className="sidebar-variable-heading" title={JSON.stringify(variable)}><span>{variableLabel(name, variable)}</span><ResourceValue name={name} variable={variable} localPath={`${selection.kind === 'block' ? `${selection.title}.` : ''}${row.name}.${name}`}/></div><VariableTrajectory localPath={`${selection.kind === 'block' ? `${selection.title}.` : ''}${row.name}.${name}`}/></div>)}</section>)}
      </div>;
  return <ResourceContext.Provider value={resourcesContext}><ResultsContext.Provider value={resultsContext}><main>
    <aside ref={sidebarRef}><div className="brand">◈ <span>MULTIFIDELITY</span></div><h1>Block explorer</h1>
      {[...model_documentStorageErrors, ...resourcesStorageErrors, ...resultStorageErrors, ...feedStorageErrors].map(message => <p key={message} className="upload-error" role="status">{message}</p>)}
      {focusSelection && selectionDetails}
      <details className={`sidebar-controls ${focusSelection ? 'collapsed-controls' : 'expanded-controls'}`} open={!focusSelection}>
        <summary>Model controls &amp; help</summary>
      <WorkspaceControls root={rootId} model_document={model_document} resources={resourcesFile?.records} results={resultFile?.catalog} feeds={feedFile?.feeds} registry={registry} onOpen={openWorkspace}/>
      <label>Block registry<select value={trail[0].definition.id} onChange={event => openRoot(event.target.value)}>{Object.keys(registry).sort().map(id => <option key={id}>{id}</option>)}</select></label>
      <button className="model_document-open" onClick={() => setMode('resources')}>Choose resources</button>
      {resourcesFile && <p className="resources-file-status">{resourcesFile.name} · {resourcesFile.records.length} records</p>}
      {unmatched.length > 0 && <details className="unmatched"><summary>{unmatched.length} unmatched variable paths</summary><p>These paths were not found in the available block definitions.</p>{unmatched.map(path => <div key={path}>{path}</div>)}</details>}
      {resourcesFile && <p>Records in other formulations appear when you explore those blocks. No values are propagated along connections.</p>}
      <button className="model_document-open" onClick={() => setMode('model_document')}>Choose model</button>
      <label>Preview formulation<select style={{ fontWeight: formulation === selectedModel?.formulation ? 700 : 400 }} value={formulation ?? ''} onChange={event => { setChoices({ ...choices, [path]: event.target.value }); setSelection(null); }}>{Object.keys(current.definition.formulations).map(name => <option key={name} value={name} style={{ fontWeight: name === selectedModel?.formulation ? 700 : 400 }}>{name}{name === selectedModel?.formulation ? ' (model)' : ''}</option>)}</select></label>
      {formulation !== selectedModel?.formulation && <button className="model_document-open" onClick={() => inspectModel([])}>View selected model</button>}
      <p className="description">{current.definition.description}</p>
      {Object.keys(current.definition.domains ?? {}).length > 0 && <div className="domain-info"><b>Index domains</b>{Object.entries(current.definition.domains).map(([name, domain]) => <div key={name}>{name} · {domain.kind}{current.domainBindings?.[name] && ` → parent.${current.domainBindings[name]}`}</div>)}<p>Indexed variables and equations are shown as families, without expanding time points or domain members.</p></div>}
      <div className="legend"><span>● Input struct</span><span>● Block</span><span>● Constraint</span><span>● Output struct</span></div>
      <p>Blue lines connect whole structs. Purple lines show equation references, pointing toward the variable declared by <code>determines</code>. Dotted orange feedback arrows trace saved replacements, from the fixed variable toward the input it replaces.</p>
      <p>Drag on empty space to box-select nodes, then drag a selected node to move the group. Pan with the middle or right mouse button. Ctrl/Cmd-click adds to the selection.</p>
      {graph.warnings.length > 0 && <div className="warnings">{graph.warnings.map(message => <p key={message}>{message}</p>)}</div>}
      </details>
      {!focusSelection && selectionDetails}
      <footer>Read-only · JSON definitions<br/>{Object.keys(registry).length} blocks in registry</footer>
    </aside>
    <div className="workspace"><div className="workspace-tabs" role="group" aria-label="Workspace mode"><button aria-pressed={mode === 'diagram'} onClick={() => setMode('diagram')}>Blocks</button><button aria-pressed={mode === 'model_document'} onClick={() => setMode('model_document')}>Model</button><button aria-pressed={mode === 'resources'} onClick={() => setMode('resources')}>Resources</button><button aria-pressed={mode === 'results'} onClick={() => setMode('results')}>Results</button><button aria-pressed={mode === 'feeds'} onClick={() => setMode('feeds')}>Feeds</button></div><nav aria-label="Block breadcrumb">{trail.map((item, index) => <React.Fragment key={index}>{index > 0 && <span>/</span>}<button onClick={() => { setTrail(trail.slice(0, index + 1)); setSelection(null); }}>{item.alias}</button></React.Fragment>)}</nav>
      {mode === 'feeds' ? <FeedsPanel key={rootId} root={rootId} file={feedFile} onChange={file => setFeedFiles(previous => ({ ...previous, [rootId]: file }))} onClear={() => setFeedFiles(previous => ({ ...previous, [rootId]: null }))}/> : mode === 'results' ? <ResultsPanel key={rootId} root={trail[0]} file={resultFile} model_document={model_document} registry={registry} resources={resourcesFile?.records} onChange={loadResults} onClear={()=>setResultFiles(previous=>({...previous,[rootId]:null}))} onUseModel={updateModel}/> : mode === 'resources' ? <ResourcesPanel key={rootId} root={trail[0]} file={resourcesFile} analysis={model_documentAnalysis} registry={registry} onChange={setResources} uploadControl={<ResourceUpload key={rootId} file={resourcesFile} root={rootId} onLoad={setResources} onClear={() => setResources(null)}/>}/> : mode === 'model_document' ? <ModelPanel key={rootId} context={trail[0]} document={model_document} analysis={model_documentAnalysis} registry={registry} onChange={updateModel} onInspect={inspectModel}/> : <>
      <div className="canvas-title"><div><small>FORMULATION</small><h2>{formulation ?? 'No formulations'}</h2></div><div className="view-toggle" role="group" aria-label="Diagram view">{['summary', 'detailed'].map(mode => <button key={mode} aria-pressed={view === mode} onClick={() => setView(mode)}>{mode === 'summary' ? 'Summary' : 'Detailed'}</button>)}</div><span>{graph.nodes.length} nodes · {visibleEdges(graph.edges, arrowVisibility).filter(edge => !edge.hidden).length} / {graph.edges.length} links</span></div>
      <div className="canvas"><SavedLayoutFlow key={`${path}:${formulation}:${view}:${JSON.stringify(replacements.pairs)}`} graph={graph} arrowVisibility={arrowVisibility} storageKey={layoutKey(current.definition.id, formulation, view)} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.15 }} minZoom={0.05} maxZoom={2} nodesConnectable={false} deleteKeyCode={null}
        selectionOnDrag selectionMode={SelectionMode.Partial} panOnDrag={[1, 2]} multiSelectionKeyCode={['Control', 'Meta']}
        onPaneClick={() => setSelection(null)}
        zoomOnDoubleClick={false}
        onNodeDoubleClick={(_, node) => { if (view === 'summary' && node.data.child && !node.data.child.unresolved) explore(node.data); }}
        onNodeClick={(event, node) => { if (event.ctrlKey || event.metaKey || event.shiftKey) return; if (view === 'detailed' && node.data.child && !node.data.child.unresolved) explore(node.data); else setSelection(node.data); }}
        onEdgeClick={(_, edge) => setSelection({ title: edge.data.kind === 'replacement' ? 'Variable replacement' : edge.label, connection: edge.data.kind === 'replacement' ? { kind: 'replacement', fixed_variable: edge.data.from, replaced_input: edge.data.to, resources_record: edge.data.recordTag } : { from: (edge.data.sourcePort ?? edge.sourceHandle)?.replace(/:out$/, ''), to: (edge.data.targetPort ?? edge.targetHandle)?.replace(/:in$/, ''), kind: edge.data.kind } })}>
        <Panel position="top-right" className="arrow-controls nodrag nopan"><fieldset><legend>Show arrows</legend>{Object.entries(arrowTypes).map(([kind, label]) => <label key={kind}><input type="checkbox" checked={arrowVisibility[kind]} onChange={event => setArrowVisibility(previous => ({...previous, [kind]: event.target.checked}))}/><span className={`arrow-swatch ${kind}`} aria-hidden="true"/>{label}</label>)}</fieldset></Panel>
        <Background color="#d8dee5" gap={22}/><Controls/><MiniMap pannable zoomable nodeColor={node => diagramColors[node.data.kind]}/>
      </SavedLayoutFlow></div></>}
    </div>
  </main></ResultsContext.Provider></ResourceContext.Provider>;
}
createRoot(document.getElementById('root')).render(<App/>);
