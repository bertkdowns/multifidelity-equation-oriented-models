// Keep source/target semantics; only choose which horizontal face each uses.
export function routeDetailedEdges(nodes, edges) {
  const byId = new Map(nodes.map(node => [node.id, node]));
  const center = node => node.position.x + (node.measured?.width ?? node.data?.width ?? 300) / 2;
  return edges.map(edge => {
    const source = byId.get(edge.source), target = byId.get(edge.target);
    if (!source || !target || source.data?.summary) return edge;
    const backwards = center(target) < center(source);
    return {
      ...edge,
      sourceHandle: backwards ? `${edge.sourceHandle}-left` : edge.sourceHandle,
      targetHandle: backwards ? `${edge.targetHandle}-right` : edge.targetHandle,
      data: { ...edge.data, sourcePort: edge.sourceHandle, targetPort: edge.targetHandle },
    };
  });
}
