import dagre from '@dagrejs/dagre';

export function resolveReference(reference, bindings, library) {
  if (reference.model_parameter) {
    return bindings[reference.model_parameter] ?? {
      definition: { id: `<${reference.model_parameter}>`, structs: {}, relationships: {} },
      bindings: {}, unresolved: true,
    };
  }
  const definition = library[reference.model];
  if (!definition) throw new Error(`Missing model definition: ${reference.model}`);
  return { definition, bindings: Object.fromEntries(Object.entries(reference.model_arguments ?? {})
    .map(([name, argument]) => [name, resolveReference(argument, bindings, library)])) };
}

export function makeGraph(context, relationshipName, library, view = 'detailed') {
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
      addNode(`model:${alias}`, 'model', alias, structs, { child, subtitle: child.definition.id });
      if (child.unresolved) warnings.push(`${alias}: generic ${ref.model_parameter} is unbound. Open a concrete wrapper to resolve it.`);
    } catch (error) { warnings.push(error.message); addNode(`model:${alias}`, 'model', alias, {}, { subtitle: error.message }); }
  }
  function link(id, from, to, label, kind) {
    if (!from || !to) { warnings.push(`Cannot resolve ${label}`); return; }
    edges.push({ id, source: from.node, target: to.node, sourceHandle: `${from.handle}:out`, targetHandle: `${to.handle}:in`,
      label, type: view === 'summary' ? 'smoothstep' : 'default', markerEnd: { type: 'arrowclosed', width: 24, height: 24, color: kind === 'connection' ? '#087f76' : '#8063ae' }, style: { stroke: kind === 'connection' ? '#0f9d92' : '#8b79bc', strokeWidth: 2.2 },
      data: { kind }, labelStyle: { fontSize: 10 }, labelBgStyle: { fill: '#fff' } });
  }
  for (const [name, equation] of Object.entries(relationship.constraints ?? {})) {
    const id = `constraint:${name}`;
    addNode(id, 'constraint', name, {}, { equation, height: 132 });
    const refs = new Set(`${equation.lhs} ${equation.rhs}`.match(/[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+/g) ?? []);
    for (const ref of refs) {
      if (ref.startsWith('units.') && !ports.has(ref)) continue;
      if (ref !== equation.determines) link(`${id}:${ref}`, ports.get(ref), { node: id, handle: 'equation' }, ref, 'dependency');
    }
    link(`${id}:determines`, { node: id, handle: 'equation' }, ports.get(equation.determines), equation.determines, 'determines');
  }
  for (const [name, connection] of Object.entries(relationship.connections ?? {}))
    link(`connection:${name}`, ports.get(connection.from), ports.get(connection.to), name, 'connection');
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
          node.data.summaryPorts.push({ id: portId, type, top: `${100 * (index + 1) / (attached.length + 1)}%` });
        });
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
  edges.forEach(edge => layout.setEdge(edge.source, edge.target, {}, edge.id));
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
