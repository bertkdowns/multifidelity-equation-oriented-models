import { resolveReference } from './graph.js';

const family = reference => reference.replace(/\[[^\]]*\]/g, '').trim();
const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);
export const selectionAt = (document, path) => path.reduce((selection, alias) => selection?.submodels?.[alias], document);
export function replaceSelection(document, path, replacement) {
  if (!path.length) return replacement;
  const [alias, ...rest] = path;
  return { ...document, submodels: { ...document.submodels, [alias]: replaceSelection(document.submodels[alias], rest, replacement) } };
}

export function defaultImplementation(context, library, relationshipName, ancestors = new Set(), budget = { remaining: 1500 }) {
  if (context.unresolved || ancestors.has(context.definition.id) || --budget.remaining < 0) return { relationship: '', submodels: {} };
  const relationship = relationshipName ?? Object.keys(context.definition.relationships)[0] ?? '';
  const next = new Set([...ancestors, context.definition.id]);
  const children = context.definition.relationships[relationship]?.models ?? {};
  return { relationship, submodels: Object.fromEntries(Object.entries(children).map(([alias, reference]) => {
    try { return [alias, defaultImplementation(resolveReference(reference, context.bindings ?? {}, library), library, undefined, next, budget)]; }
    catch { return [alias, { relationship: '', submodels: {} }]; }
  })) };
}

export function parseImplementation(text, { allowIncomplete = false } = {}) {
  const document = JSON.parse(text);
  let count = 0;
  function check(selection, path, depth) {
    if (++count > 1500 || depth > 50) throw Error('Implementation exceeds 1500 model occurrences or 50 levels.');
    if (!isObject(selection) || Object.keys(selection).some(key => !['relationship', 'submodels'].includes(key)))
      throw Error(`${path}: expected relationship and optional submodels only. Select the root model separately.`);
    if (typeof selection.relationship !== 'string' || (!allowIncomplete && !selection.relationship)) throw Error(`${path}: missing relationship.`);
    if (selection.submodels !== undefined && !isObject(selection.submodels)) throw Error(`${path}: submodels must be an object.`);
    return { relationship: selection.relationship, submodels: Object.fromEntries(Object.entries(selection.submodels ?? {}).map(([alias, child]) => [alias, check(child, `${path}.${alias}`, depth + 1)])) };
  }
  return check(document, 'root', 0);
}

// Declaration coverage, matching requirements.py: only the parent can supply a
// child's input. This does not compile equations, convert units or solve a model.
export function analyzeImplementation(context, document, library) {
  const inputs = [], initial = [], occurrences = [], errors = [];
  let remaining = 1500;
  function visit(model, selection, path, supplied, depth) {
    const location = path.length ? path.join('.') : model.definition.id;
    if (--remaining < 0 || depth > 50) { errors.push(`${location}: implementation is too large or deeply nested.`); return; }
    if (model.unresolved) { errors.push(`${location}: unbound generic model. Choose a concrete root wrapper.`); return; }
    const relationship = model.definition.relationships[selection?.relationship];
    occurrences.push({ path, context: model, selection });
    if (!relationship) { errors.push(`${location}: choose a valid relationship.`); return; }
    const children = {};
    for (const [alias, reference] of Object.entries(relationship.models ?? {})) {
      try { children[alias] = resolveReference(reference, model.bindings ?? {}, library); }
      catch (error) { errors.push(`${location}.${alias}: ${error.message}`); }
    }
    const expected = Object.keys(relationship.models ?? {}).sort();
    if (JSON.stringify(Object.keys(selection.submodels ?? {}).sort()) !== JSON.stringify(expected))
      errors.push(`${location}: submodels must be exactly ${expected.join(', ') || '(none)'}.`);
    const targets = new Set();
    const outputs = new Set();
    const allowed = new Set();
    for (const [name, struct] of Object.entries(model.definition.structs)) {
      for (const [variable, metadata] of Object.entries(struct.variables)) {
        const local = `${name}.${variable}`;
        if (struct.direction === 'output') { allowed.add(local); outputs.add(local); }
        else if (!supplied.has(local)) inputs.push({ path: [...path, name, variable].join('.'), occurrence: path.join('.'), struct: name, name: variable, variable: metadata });
      }
    }
    for (const [alias, child] of Object.entries(children))
      for (const [name, struct] of Object.entries(child.definition.structs))
        if (struct.direction === 'input') for (const variable of Object.keys(struct.variables)) allowed.add(`${alias}.${name}.${variable}`);
    function register(reference) {
      const target = family(reference);
      if (!allowed.has(target)) errors.push(`${location}: invalid determination target ${reference}.`);
      if (targets.has(target)) errors.push(`${location}: duplicate determination of ${target}.`);
      targets.add(target);
    }
    for (const equation of Object.values(relationship.constraints ?? {})) register(equation.determines);
    for (const derivative of Object.values(relationship.derivatives ?? {})) {
      register(derivative.determines);
      const [struct, variable] = derivative.determines.split('.');
      const metadata = model.definition.structs[struct]?.variables[variable];
      if (metadata) initial.push({ path: [...path, struct, variable].join('.'), occurrence: path.join('.'), struct, name: variable, variable: metadata });
    }
    for (const connection of Object.values(relationship.connections ?? {})) {
      const parts = connection.to.split('.');
      const struct = parts.length === 1 ? model.definition.structs[parts[0]] : children[parts[0]]?.definition.structs[parts[1]];
      if (!struct) errors.push(`${location}: unknown connection target ${connection.to}.`);
      else for (const variable of Object.keys(struct.variables)) register(`${connection.to}.${variable}`);
    }
    if (relationship.external) for (const target of Object.keys(relationship.external.dependencies)) register(target);
    for (const output of outputs) if (!targets.has(output)) errors.push(`${location}: missing output determination ${output}.`);
    for (const [alias, child] of Object.entries(children)) {
      const prefix = `${alias}.`;
      const childSupplied = new Set([...targets].filter(target => target.startsWith(prefix)).map(target => target.slice(prefix.length)));
      visit(child, selection.submodels?.[alias], [...path, alias], childSupplied, depth + 1);
    }
  }
  visit(context, document, [], new Set(), 0);
  return { inputs: inputs.sort((a, b) => a.path.localeCompare(b.path)), initial: initial.sort((a, b) => a.path.localeCompare(b.path)), occurrences, errors };
}
