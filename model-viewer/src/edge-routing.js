// Keep source/target semantics; only choose which horizontal face each uses.
export function routeDetailedEdges(nodes, edges) {
  const byId = new Map(nodes.map(node => [node.id, node]));
  const center = node => node.position.x + (node.measured?.width ?? node.data?.width ?? 300) / 2;
  return edges.map(edge => {
    const source = byId.get(edge.source), target = byId.get(edge.target);
    if (!source || !target || source.data?.summary) return edge;
    const feedbackLoop = edge.data?.kind === 'replacement' && edge.source === edge.target;
    const backwards = !feedbackLoop && center(target) < center(source);
    return {
      ...edge,
      sourceHandle: backwards ? `${edge.sourceHandle}-left` : edge.sourceHandle,
      targetHandle: backwards || feedbackLoop ? `${edge.targetHandle}-right` : edge.targetHandle,
      data: { ...edge.data, sourcePort: edge.sourceHandle, targetPort: edge.targetHandle },
    };
  });
}


// Replacement ports use the axis perpendicular to the process ports. Internal
// feedback loops share the top face so the return path stays outside the unit.
export function summaryPortSide(port) {
  if (port.replacement) return port.type === 'source' || port.feedback ? 'top' : 'bottom';
  return port.type === 'source' ? 'right' : 'left';
}

export function summaryPortGeometry(port, data) {
  const sides = ['right', 'bottom', 'left', 'top'];
  let side = summaryPortSide(port);
  const fraction = parseFloat(port.top) / 100;
  let [x, y] = {right: [1, fraction], bottom: [fraction, 1],
                left: [0, fraction], top: [fraction, 0]}[side];
  if (data.kind === 'model') {
    if (data.flipped) {
      x = 1 - x;
      if (side === 'right') side = 'left';
      else if (side === 'left') side = 'right';
    }
    for (let turn = 0; turn < (data.rotation ?? 0); turn++) {
      [x, y] = [1 - y, x];
      side = sides[(sides.indexOf(side) + 1) % 4];
    }
  }
  const horizontal = side === 'top' || side === 'bottom';
  return {side, style: {[horizontal ? 'left' : 'top']: `${100 * (horizontal ? x : y)}%`}};
}
