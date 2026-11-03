export function layoutKey(model, relationship, view) {
  return `multifidelity:layout:v1:${JSON.stringify([model, relationship, view])}`;
}

export function restorePositions(nodes, key, storage) {
  try {
    storage ??= globalThis.localStorage;
    const saved = JSON.parse(storage.getItem(key) ?? '{}');
    return nodes.map(node => {
      const position = saved?.[node.id];
      let restored = Number.isFinite(position?.x) && Number.isFinite(position?.y)
        ? { ...node, position: { x: position.x, y: position.y } } : node;
      if (typeof position?.flipped === 'boolean' && Number.isInteger(position?.rotation) && position.rotation >= 0 && position.rotation < 4)
        restored = { ...restored, data: { ...restored.data, flipped: position.flipped, rotation: position.rotation } };
      return restored;
    });
  } catch {
    return nodes;
  }
}

export function savePositions(nodes, key, storage) {
  try {
    storage ??= globalThis.localStorage;
    storage.setItem(key, JSON.stringify(Object.fromEntries(nodes.map(node => [node.id, {
      ...node.position,
      ...(typeof node.data?.flipped === 'boolean' && Number.isInteger(node.data?.rotation)
        ? { flipped: node.data.flipped, rotation: node.data.rotation } : {}),
    }]))));
  } catch {
    // Browsers may disable storage or run out of space; dragging still works.
  }
}
