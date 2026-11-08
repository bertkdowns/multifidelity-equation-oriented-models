import { parseImplementation } from './implementation.js';

const object = x => x !== null && typeof x === 'object' && !Array.isArray(x);
const text = x => typeof x === 'string' && x.length > 0;
function keys(value, allowed, required = allowed) {
  if (!object(value) || Object.keys(value).some(k => !allowed.includes(k)) || required.some(k => !(k in value))) throw Error('Unexpected or missing document fields.');
}
export function parseResults(source) {
  const doc = JSON.parse(source);
  keys(doc, ['schema_version','run_id','created_at','model_id','implementation','mode','time_unit','solve','specification','variables'], ['schema_version','run_id','created_at','model_id','implementation','mode','time_unit','solve','variables']);
  if (doc.schema_version !== 1) throw Error('Unsupported results schema version.');
  if (![doc.run_id,doc.model_id,doc.time_unit].every(text)) throw Error('Missing run, model or time-unit identity.');
  if (!text(doc.created_at) || !/(Z|[+-]\d{2}:\d{2})$/.test(doc.created_at) || !Number.isFinite(Date.parse(doc.created_at))) throw Error('created_at must be a timestamp with a timezone.');
  if (!['steady','dynamic'].includes(doc.mode)) throw Error('Invalid model mode.');
  const implementation = parseImplementation(JSON.stringify(doc.implementation));
  keys(doc.solve, ['status','termination_condition','solver','message'], ['status']);
  if (!['optimal','feasible','failed','not_solved'].includes(doc.solve.status)) throw Error('Invalid solve status.');
  for (const key of ['termination_condition','solver','message']) if (doc.solve[key] != null && typeof doc.solve[key] !== 'string') throw Error(`Invalid solve ${key}.`);
  if (doc.specification != null) {
    keys(doc.specification,['specifications','initial_values'],[]);
    const ids=[];
    for (const key of ['specifications','initial_values']) {
      const list=doc.specification[key] ?? [];
      if (!Array.isArray(list) || !list.every(text)) throw Error('Invalid specification record IDs.');
      ids.push(...list);
    }
    if (new Set(ids).size !== ids.length) throw Error('Duplicate specification record IDs.');
  }
  if (!Array.isArray(doc.variables)) throw Error('Expected result variable families.');
  const paths = new Set();
  for (const variable of doc.variables) {
    keys(variable,['variable_path','unit','dimensions','entries']);
    if (!text(variable.variable_path) || !text(variable.unit) || paths.has(variable.variable_path)) throw Error('Invalid or duplicate result path.');
    paths.add(variable.variable_path);
    if (!Array.isArray(variable.dimensions) || !variable.dimensions.every(text) || new Set(variable.dimensions).size !== variable.dimensions.length) throw Error(`${variable.variable_path}: invalid dimensions.`);
    if (!Array.isArray(variable.entries) || !variable.entries.length) throw Error(`${variable.variable_path}: missing entries.`);
    const coordinates=new Set();
    for (const entry of variable.entries) {
      keys(entry,['index','value','fixed','issue'],['index','value','fixed']);
      if (!Array.isArray(entry.index) || entry.index.length !== variable.dimensions.length || !entry.index.every(x => typeof x === 'string' || (typeof x === 'number' && Number.isFinite(x)))) throw Error(`${variable.variable_path}: invalid index coordinates.`);
      const key=JSON.stringify(entry.index);
      if (coordinates.has(key)) throw Error(`${variable.variable_path}: duplicate coordinates.`);
      coordinates.add(key);
      if (typeof entry.fixed !== 'boolean') throw Error('Entry fixed must be boolean.');
      if (entry.value === null) {
        if (!['unset','nonfinite'].includes(entry.issue)) throw Error('Unavailable values require an explicit issue.');
      } else if (typeof entry.value !== 'number' || !Number.isFinite(entry.value) || entry.issue != null) throw Error('Expected a finite value or an explicit unavailable entry.');
    }
  }
  return {...doc, implementation};
}
export function sameImplementation(a,b) {
  if (!a || !b || a.relationship !== b.relationship) return false;
  const ak=Object.keys(a.submodels ?? {}).sort(), bk=Object.keys(b.submodels ?? {}).sort();
  return JSON.stringify(ak) === JSON.stringify(bk) && ak.every(k=>sameImplementation(a.submodels[k],b.submodels[k]));
}
export const indexResults = document => new Map((document?.variables ?? []).map(v=>[v.variable_path,v]));
export const resultNumber = entry => entry.value === null ? `Unavailable (${entry.issue})` : Number(entry.value.toPrecision(8)).toString();
export const resultPreview = variable => variable.entries.length === 1 ? resultNumber(variable.entries[0]) : `${variable.entries.length} indexed values`;
// Preserve existing order within fixed, mixed, and free groups.
export function fixedFirst(items) {
  const rank = item => {
    const entries = item.entries ?? [item];
    return entries.every(entry => entry.fixed) ? 0 : entries.some(entry => entry.fixed) ? 1 : 2;
  };
  return [...items].sort((a, b) => rank(a) - rank(b));
}
