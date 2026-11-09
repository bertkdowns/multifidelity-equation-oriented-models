import dagre from '@dagrejs/dagre';
import { diagramColors } from './diagram-theme.js';
import { summaryPortSide } from './edge-routing.js';

export const variableLabel = (name, variable) => variable.dimensions?.length ? `${name}[${variable.dimensions.join(', ')}]` : name;
const family = reference => reference.replace(/\[[^\]]*\]/g, '').trim();

export function resolveReference(reference, bindings, library) {
  if (reference.model_parameter) {
    const argument = bindings[reference.model_parameter];
    return argument ? { ...argument, domainBindings: reference.domain_bindings ?? {} } : {
      definition: { id: `<${reference.model_parameter}>`, structs: {}, relationships: {} },
      bindings: {}, unresolved: true,
    };
  }
  const definition = library[reference.model];
  if (!definition) throw new Error(`Missing model definition: ${reference.model}`);
  return { definition, domainBindings: reference.domain_bindings ?? {}, bindings: Object.fromEntries(Object.entries(reference.model_arguments ?? {})
    .map(([name, argument]) => [name, resolveReference(argument, bindings, library)])) };
}

export function makeGraph(context, relationshipName, library, view = 'detailed', replacements = [], prefix = '') {
  const { definition, bindings = {} } = context;
  const relationship = definition.relationships[relationshipName];
  const nodes = [], edges = [], warnings = [];
  if (!relationship) return { nodes, edges, warnings };
  const ports = new Map();
  function addNode(id, kind, title, structs, extra = {}) {
    const rows = [];
    for (const [name, struct] of Object.entries(structs)) {
      const prefix = kind === 'model' ? `${title}.` : '';
      ports.set(prefix + name, { node: id, handle: name });
      rows.push({ name, direction: struct.direction, variables: struct.variables });
      for (const variable of Object.keys(struct.variables))
        ports.set(`${prefix}${name}.${variable}`, { node: id, handle: `${name}.${variable}` });
    }
    const height = 75 + rows.reduce((sum, row) => sum + 31 + Object.keys(row.variables).length * 23, 0);
    nodes.push({ id, type: 'entity', position: { x: 0, y: 0 }, data: { kind, title, rows, height, ...extra, summary: view === 'summary' } });
  }
  for (const [name, struct] of Object.entries(definition.structs))
    addNode(`struct:${name}`, struct.direction, name, { [name]: struct });
  for (const [alias, ref] of Object.entries(relationship.models ?? {})) {
    try {
      const child = resolveReference(ref, bindings, library);
      const structs = child.unresolved ? definition.model_parameters?.[ref.model_parameter]?.requires ?? {} : child.definition.structs;
      addNode(`model:${alias}`, 'model', alias, structs, { child, subtitle: child.definition.id, domains: child.definition.domains ?? {}, domainBindings: ref.domain_bindings ?? {} });
      if (child.unresolved) warnings.push(`${alias}: generic ${ref.model_parameter} is unbound. Open a concrete wrapper to resolve it.`);
    } catch (error) { warnings.push(error.message); addNode(`model:${alias}`, 'model', alias, {}, { subtitle: error.message }); }
  }
  function link(id, from, to, label, kind) {
    if (!from || !to) { warnings.push(`Cannot resolve ${label}`); return; }
    edges.push({ id, source: from.node, target: to.node, sourceHandle: `${from.handle}:out`, targetHandle: `${to.handle}:in`,
      label, type: view === 'summary' ? 'smoothstep' : 'default', markerEnd: { type: 'arrowclosed', width: 24, height: 24, color: diagramColors[kind === 'connection' ? 'connection' : 'dependency'] }, style: { stroke: diagramColors[kind === 'connection' ? 'connection' : 'dependency'], strokeWidth: 2.2 },
      data: { kind }, labelStyle: { fontSize: 10 }, labelBgStyle: { fill: '#fff' } });
  }
  const equations = { ...relationship.constraints };
  for (const [name, derivative] of Object.entries(relationship.derivatives ?? {})) {
    equations[`derivative:${name}`] = {
      lhs: `d(${derivative.state})/d(${derivative.with_respect_to})`, rhs: derivative.rate,
      determines: derivative.determines, derivative,
    };
  }
  for (const [name, equation] of Object.entries(equations)) {
    const id = `constraint:${name}`;
    addNode(id, 'constraint', equation.derivative ? name.slice('derivative:'.length) : name, {}, { equation, height: 132 });
    const refs = new Set(`${equation.lhs} ${equation.rhs}`.match(/[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+(?:\[[^\]]+\])?/g) ?? []);
    for (const ref of refs) {
      if (ref.startsWith('units.') && !ports.has(ref)) continue;
      if (family(ref) !== family(equation.determines)) link(`${id}:${ref}`, ports.get(family(ref)), { node: id, handle: 'equation' }, ref, 'dependency');
    }
    link(`${id}:determines`, { node: id, handle: 'equation' }, ports.get(family(equation.determines)), equation.determines, 'determines');
  }
  for (const [name, connection] of Object.entries(relationship.connections ?? {}))
    link(`connection:${name}`, ports.get(connection.from), ports.get(connection.to), name, 'connection');
  // Project descendant variables onto their containing visible model. Their
  // full paths remain on the edge, so drilling down never changes the pair.
  function replacementPort(path) {
    if (prefix && !path.startsWith(`${prefix}.`)) return null;
    const local = prefix ? path.slice(prefix.length + 1) : path;
    if (ports.has(local)) return ports.get(local);
    const alias = local.split('.')[0];
    const node = nodes.find(node => node.id === `model:${alias}`);
    if (!node || node.data.child?.unresolved || local.split('.').length < 3) return null;
    const handle = `replacement:${local}`;
    return { node: node.id, handle };
  }
  for (const pair of replacements) {
    const from = replacementPort(pair.from), to = replacementPort(pair.to);
    // A cross-boundary pair is visible at its common ancestor, not a made-up
    // external variable in a child-only diagram.
    if (!from || !to) continue;
    for (const endpoint of [from, to]) {
      if (!endpoint.handle.startsWith('replacement:')) continue;
      const node = nodes.find(node => node.id === endpoint.node);
      node.data.replacementPorts ??= [];
      if (!node.data.replacementPorts.includes(endpoint.handle)) node.data.replacementPorts.push(endpoint.handle);
    }
    edges.push({
      id: `replacement:${pair.recordId}`, source: from.node, target: to.node,
      sourceHandle: `${from.handle}:out`, targetHandle: `${to.handle}:in`,
      ariaLabel: `${pair.from} replaces ${pair.to}`, type: 'smoothstep',
      markerEnd: { type: 'arrow', width: 24, height: 24, color: diagramColors.replacement, strokeWidth: 2 },
      style: { stroke: diagramColors.replacement, strokeWidth: 2, strokeDasharray: '2 6', strokeLinecap: 'round' },
      className: 'replacement-edge',
      data: { kind: 'replacement', ...pair },
      labelStyle: { fontSize: 10, fill: diagramColors.replacement }, labelBgStyle: { fill: diagramColors.replacementSurface },
    });
  }
  if (view === 'summary') {
    for (const node of nodes) {
      node.data.summaryPorts = [];
      // Follow the declared interface, independently of surrounding edge order.
      const portOrder = new Map();
      for (const row of node.data.rows) {
        portOrder.set(row.name, portOrder.size);
        for (const variable of Object.keys(row.variables))
          portOrder.set(`${row.name}.${variable}`, portOrder.size);
      }
      for (const [type, endpoint, handle] of [['target', 'target', 'targetHandle'], ['source', 'source', 'sourceHandle']]) {
        const attached = edges.filter(edge => edge[endpoint] === node.id);
        const order = edge => portOrder.get(edge[handle].replace(/:(in|out)$/, '')) ?? Number.MAX_SAFE_INTEGER;
        attached.sort((a, b) => order(a) - order(b));
        attached.forEach((edge, index) => {
          const originalHandle = edge[handle];
          const portId = `summary:${type}:${index}`;
          edge.data[`${type}Port`] = originalHandle;
          edge[handle] = portId;
          node.data.summaryPorts.push({ id: portId, type, top: `${100 * (index + 1) / (attached.length + 1)}%`, replacement: edge.data.kind === 'replacement', feedback: type === 'target' && edge.data.kind === 'replacement' && edge.source === edge.target });
        });
      }
      // Space each face independently: feedback ports must not consume slots
      // on the process inlet/outlet faces, even when both ends use one unit.
      for (const side of ['left', 'right', 'top', 'bottom']) {
        const face = node.data.summaryPorts.filter(port => summaryPortSide(port) === side);
        face.forEach((port, index) => { port.top = `${100 * (index + 1) / (face.length + 1)}%`; });
      }
    }
  }
  const layout = new dagre.graphlib.Graph({ multigraph: true }).setGraph({ rankdir: 'LR', nodesep: 55, ranksep: 170 }).setDefaultEdgeLabel(() => ({}));
  nodes.forEach(node => {
    const compact = node.data.summary && node.data.kind !== 'constraint';
    node.data.width = compact ? 180 : 300;
    if (node.data.summary && node.data.kind === 'constraint') node.data.height = 85;
    if (compact) node.data.height = node.data.kind === 'model' ? 170 : 85;
    layout.setNode(node.id, { width: node.data.width, height: node.data.height });
  });
  // Feedback annotations must not change the underlying process layout.
  edges.filter(edge => edge.data.kind !== 'replacement').forEach(edge => layout.setEdge(edge.source, edge.target, {}, edge.id));
  dagre.layout(layout);
  nodes.forEach(node => { const pos = layout.node(node.id); node.position = { x: pos.x - node.data.width / 2, y: pos.y - node.data.height / 2 }; });
  if (view === 'summary') {
    const columns = new Map();
    for (const node of nodes) {
      const column = layout.node(node.id).x;
      if (!columns.has(column)) columns.set(column, []);
      columns.get(column).push(node);
    }
    for (const column of columns.values()) {
      column.sort((a, b) => a.position.y - b.position.y);
      column.forEach((node, index) => { node.position.x += index * 10; });
    }
  }
  return { nodes, edges, warnings: [...new Set(warnings)] };
}
