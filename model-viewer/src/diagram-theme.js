// Semantic colours shared by the canvas, CSS, legend and minimap.
export const diagramColors = Object.freeze({
  input: '#148577', inputSurface: '#e8f5f1',
  model: '#748296', modelSurface: '#f3f5f8',
  constraint: '#917da5', constraintSurface: '#f4f0f7',
  output: '#829bb2', outputSurface: '#ffffff',
  specified: '#216b48', specifiedSurface: '#e5f3e9',
  solved: '#526f8b', solvedSurface: '#eff4f9',
  connection: '#287db0', dependency: '#917da5',
  replacement: '#c06616', replacementSurface: '#fff8ee',
});

export const arrowTypes = Object.freeze({
  connection: 'Connections', dependency: 'Constraint dependencies', replacement: 'Replacements',
});
const storageKey = 'multifidelity:canvas-arrows:v1';
const defaults = () => Object.fromEntries(Object.keys(arrowTypes).map(kind => [kind, true]));
export function loadArrowVisibility(storage) {
  try {
    const saved = JSON.parse((storage ?? globalThis.localStorage).getItem(storageKey));
    return Object.fromEntries(Object.keys(arrowTypes).map(kind => [kind, typeof saved?.[kind] === 'boolean' ? saved[kind] : true]));
  } catch { return defaults(); }
}
export function saveArrowVisibility(visibility, storage) {
  try { (storage ?? globalThis.localStorage).setItem(storageKey, JSON.stringify(visibility)); }
  catch { /* Controls remain usable when browser storage is unavailable. */ }
}
export function visibleEdges(edges, visibility) {
  return edges.map(edge => ({ ...edge, hidden: visibility[edge.data.kind === 'determines' ? 'dependency' : edge.data.kind] === false }));
}
