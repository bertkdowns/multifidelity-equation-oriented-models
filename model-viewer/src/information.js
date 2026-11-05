import { resolveReference } from './graph.js';

const types = new Set(['sensor_reading', 'control_setpoint', 'equipment_specification', 'parameter', 'assumption']);
export const informationTypes = [...types];
const fields = new Set(['id', 'tag', 'information_type', 'variable_path', 'type', 'value', 'unit', 'standard_deviation', 'trust_rank']);
export function valueShape(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return [];
  if (!Array.isArray(value) || !value.length) throw Error('Values must be finite numbers or nonempty numeric arrays.');
  const shapes = value.map(valueShape);
  if (shapes.some(shape => JSON.stringify(shape) !== JSON.stringify(shapes[0]))) throw Error('Series arrays must be rectangular.');
  return [value.length, ...shapes[0]];
}

export function parseInformation(text) {
  const records = JSON.parse(text);
  if (!Array.isArray(records)) throw Error('Expected an array of information records.');
  const ids = new Set();
  return records.map((record, index) => {
    try {
      if (!record || typeof record !== 'object' || Array.isArray(record)) throw Error('Expected a record object.');
      if (Object.keys(record).some(key => !fields.has(key))) throw Error('Unknown record field.');
      for (const field of ['id', 'tag', 'variable_path', 'unit'])
        if (typeof record[field] !== 'string' || !record[field].trim()) throw Error(`Missing or invalid ${field}.`);
      if (ids.has(record.id)) throw Error(`Duplicate record ID: ${record.id}`);
      if (!types.has(record.information_type)) throw Error('Invalid information_type.');
      if (!Number.isInteger(record.trust_rank) || record.trust_rank < 1 || record.trust_rank > 10) throw Error('trust_rank must be an integer from 1 to 10.');
      if (record.standard_deviation != null && (typeof record.standard_deviation !== 'number' || !Number.isFinite(record.standard_deviation) || record.standard_deviation < 0)) throw Error('Invalid standard_deviation.');
      const type = record.type === undefined ? 'constant' : record.type;
      const shape = valueShape(record.value);
      if (!['constant', 'series'].includes(type) || (type === 'constant') !== (shape.length === 0)) throw Error('Constants require a number; series require an array.');
      ids.add(record.id);
      return { ...record, type };
    } catch (error) { throw Error(`Record ${index + 1}: ${error.message}`); }
  });
}

export function indexInformation(records) {
  const index = new Map();
  for (const record of records) {
    if (!index.has(record.variable_path)) index.set(record.variable_path, []);
    index.get(record.variable_path).push(record);
  }
  for (const candidates of index.values()) candidates.sort((a, b) => b.trust_rank - a.trust_rank || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  return index;
}

export function informationPreview(record) {
  if (record.type === 'series') {
    const shape = valueShape(record.value);
    return shape.length === 1 ? `Series · ${shape[0]} samples` : `Array · ${shape.join(' × ')}`;
  }
  return Number(record.value.toPrecision(6)).toString();
}

export function appendInformation(records, draft) {
  let value;
  try { value = JSON.parse(draft.value); }
  catch { throw Error('Value must be a JSON number or numeric array, for example 12.5 or [1, 2, 3].'); }
  if (draft.standard_deviation.trim() && !Number.isFinite(Number(draft.standard_deviation)))
    throw Error('Standard deviation must be a finite nonnegative number.');
  const record = {
    id: draft.id.trim(), tag: draft.tag.trim(), variable_path: draft.variable_path.trim(),
    information_type: draft.information_type, type: draft.type, value,
    unit: draft.unit.trim(), trust_rank: Number(draft.trust_rank),
    ...(draft.standard_deviation.trim() ? { standard_deviation: Number(draft.standard_deviation) } : {}),
  };
  // Validate the complete replacement before publishing, including unique IDs.
  return parseInformation(JSON.stringify([...records, record]));
}

// Resolve only the finite authored path, trying alternatives without expanding
// recursive definitions. A definition browser has no selected implementation.
export function findVariable(context, path, library) {
  const parts = path.split('.');
  if (parts.length === 2) return context.definition.structs[parts[0]]?.variables[parts[1]];
  if (parts.length < 2) return undefined;
  for (const relationship of Object.values(context.definition.relationships)) {
    const reference = relationship.models?.[parts[0]];
    if (!reference) continue;
    try {
      const child = resolveReference(reference, context.bindings ?? {}, library);
      const variable = findVariable(child, parts.slice(1).join('.'), library);
      if (variable) return variable;
    } catch { /* Another alternative may resolve this occurrence. */ }
  }
}
