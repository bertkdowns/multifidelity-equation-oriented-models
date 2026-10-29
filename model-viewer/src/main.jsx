import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ReactFlow, Handle, Position, Background, Controls, MiniMap, useUpdateNodeInternals } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import './style.css';
import { makeGraph } from './graph.js';

const documents = import.meta.glob('../../src/multifidelity/model_language/models/*.json', { eager: true, import: 'default' });
const library = Object.fromEntries(Object.values(documents).map(model => [model.id, model]));
const modelIcons = new Set(Object.keys(import.meta.glob('../public/model-icons/*.svg')).map(path => path.split('/').at(-1).replace(/\.svg$/, '')));

function Port({ id }) {
  return <><Handle type="target" position={Position.Left} id={`${id}:in`} isConnectable={false}/><Handle type="source" position={Position.Right} id={`${id}:out`} isConnectable={false}/></>;
}
function Entity({ id, data, selected }) {
  const [structsCollapsed, setStructsCollapsed] = useState(false);
  const [collapsedRows, setCollapsedRows] = useState({});
  const [flipped, setFlipped] = useState(false);
  const [rotation, setRotation] = useState(0);
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
      {data.kind !== 'model' && <small>{data.kind === 'constraint' ? 'CONSTRAINT' : `${data.kind.toUpperCase()} STRUCT`}</small>}
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
      return <Handle key={port.id} id={port.id} type={port.type} position={side} style={horizontal ? { left: port.top } : { top: port.top }} isConnectable={false}/>;
    })}
    {!data.summary && data.kind === 'model' && data.rows.length > 0 && <div className="struct-list-toggle">
      <button className="nodrag nopan" aria-expanded={!structsCollapsed} onClick={event => { event.stopPropagation(); setStructsCollapsed(!structsCollapsed); }}>{structsCollapsed ? '▸' : '▾'} Structs <span>{data.rows.length}</span></button>
      {structsCollapsed && data.rows.map(row => <React.Fragment key={row.name}>{hiddenPorts(row)}</React.Fragment>)}
    </div>}
    {data.equation ? <div className="equation">{!data.summary && <Port id="equation"/>}<code>{data.equation.lhs} = {data.equation.rhs}</code><small>Determines {data.equation.determines}</small></div> : !data.summary && !structsCollapsed && data.rows.map(row => <section key={row.name}>
      <div className="struct">
        {collapsedRows[row.name] ? hiddenPorts(row) : <Port id={row.name}/>}
        <button className="nodrag nopan" aria-expanded={!collapsedRows[row.name]} onClick={event => { event.stopPropagation(); setCollapsedRows(previous => ({ ...previous, [row.name]: !previous[row.name] })); }}>{collapsedRows[row.name] ? '▸' : '▾'} {row.name} <span>({Object.keys(row.variables).length})</span></button><small>{row.direction}</small>
      </div>
      {!collapsedRows[row.name] && Object.entries(row.variables).map(([name, variable]) => <div className="variable" key={name} title={JSON.stringify(variable)}><Port id={`${row.name}.${name}`}/><span>{name}</span><code>{variable.unit ?? 'dimensionless'}</code></div>)}
    </section>)}
  </article>;
}
const nodeTypes = { entity: Entity };
function App() {
  const [trail, setTrail] = useState([{ definition: library.steam_generating_heat_pump, bindings: {}, alias: 'steam_generating_heat_pump' }]);
  const current = trail.at(-1);
  const [choices, setChoices] = useState({});
  const [view, setView] = useState('detailed');
  const path = trail.map(item => item.alias).join('/');
  const relationship = choices[path] ?? Object.keys(current.definition.relationships)[0];
  const graph = useMemo(() => makeGraph(current, relationship, library, view), [current, relationship, view]);
  const [selection, setSelection] = useState(null);
  function explore(data) { setTrail([...trail, { ...data.child, alias: data.title }]); setSelection(null); }
  function openRoot(id) { setTrail([{ definition: library[id], bindings: {}, alias: id }]); setSelection(null); }
  return <main>
    <aside><div className="brand">◈ <span>MULTIFIDELITY</span></div><h1>Model explorer</h1><p>Follow the equations.<br/>Explore every level.</p>
      <label>Model library<select value={trail[0].definition.id} onChange={event => openRoot(event.target.value)}>{Object.keys(library).sort().map(id => <option key={id}>{id}</option>)}</select></label>
      <label>Relationship<select value={relationship ?? ''} onChange={event => { setChoices({ ...choices, [path]: event.target.value }); setSelection(null); }}>{Object.keys(current.definition.relationships).map(name => <option key={name}>{name}</option>)}</select></label>
      <p className="description">{current.definition.description}</p>
      <div className="legend"><span>● Input struct</span><span>● Model</span><span>● Constraint</span><span>● Output struct</span></div>
      <p>Teal lines connect whole structs. Purple lines show equation references, pointing toward the variable declared by <code>determines</code>.</p>
      {graph.warnings.length > 0 && <div className="warnings">{graph.warnings.map(message => <p key={message}>{message}</p>)}</div>}
      {selection && <div className="details"><h3>{selection.title}</h3>
        {selection.child && !selection.child.unresolved && <button className="explore-button" onClick={() => explore(selection)}>Explore model →</button>}
        {selection.equation || selection.connection ? <pre>{JSON.stringify(selection.equation ?? selection.connection, null, 2)}</pre> : selection.rows.map(row => <section className="sidebar-struct" key={row.name}><h4>{row.name} <small>{row.direction}</small></h4>{Object.entries(row.variables).map(([name, variable]) => <div key={name} title={JSON.stringify(variable)}><span>{name}</span><code>{variable.unit ?? 'dimensionless'}</code></div>)}</section>)}
      </div>}
      <footer>Read-only · JSON definitions<br/>{Object.keys(library).length} models in library</footer>
    </aside>
    <div className="workspace"><nav aria-label="Model breadcrumb">{trail.map((item, index) => <React.Fragment key={index}>{index > 0 && <span>/</span>}<button onClick={() => { setTrail(trail.slice(0, index + 1)); setSelection(null); }}>{item.alias}</button></React.Fragment>)}</nav>
      <div className="canvas-title"><div><small>RELATIONSHIP</small><h2>{relationship ?? 'No relationships'}</h2></div><div className="view-toggle" role="group" aria-label="Diagram view">{['summary', 'detailed'].map(mode => <button key={mode} aria-pressed={view === mode} onClick={() => setView(mode)}>{mode === 'summary' ? 'Summary' : 'Detailed'}</button>)}</div><span>{graph.nodes.length} nodes · {graph.edges.length} links</span></div>
      <div className="canvas"><ReactFlow key={`${path}:${relationship}:${view}`} defaultNodes={graph.nodes} defaultEdges={graph.edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.15 }} minZoom={0.05} maxZoom={2} nodesConnectable={false} deleteKeyCode={null}
        onNodeClick={(_, node) => { if (view === 'detailed' && node.data.child && !node.data.child.unresolved) explore(node.data); else setSelection(node.data); }}
        onEdgeClick={(_, edge) => setSelection({ title: edge.label, connection: { from: (edge.data.sourcePort ?? edge.sourceHandle)?.replace(/:out$/, ''), to: (edge.data.targetPort ?? edge.targetHandle)?.replace(/:in$/, ''), kind: edge.data.kind } })}>
        <Background color="#d8dee5" gap={22}/><Controls/><MiniMap pannable zoomable nodeColor={node => ({ model: '#608ce6', constraint: '#ac8fd2', input: '#53b5ac', output: '#e4ae62' })[node.data.kind]}/>
      </ReactFlow></div>
    </div>
  </main>;
}
createRoot(document.getElementById('root')).render(<App/>);
