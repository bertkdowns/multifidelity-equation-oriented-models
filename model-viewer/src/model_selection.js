import { resolveReference } from './graph.js';

const family = reference => reference.replace(/\[[^\]]*\]/g, '').trim();
const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);
export const selectionAt = (catalog, path) => path.reduce((selection, alias) => selection?.subblocks?.[alias], catalog);
export function replaceSelection(catalog, path, replacement) {
  if (!path.length) return replacement;
  const [alias, ...rest] = path;
  return { ...catalog, subblocks: { ...catalog.subblocks, [alias]: replaceSelection(catalog.subblocks[alias], rest, replacement) } };
}

export function defaultModel(context, registry, formulationName, ancestors = new Set(), budget = { remaining: 1500 }) {
  if (context.unresolved || ancestors.has(context.definition.id) || --budget.remaining < 0) return { formulation: '', subblocks: {} };
  const formulation = formulationName ?? Object.keys(context.definition.formulations)[0] ?? '';
  const next = new Set([...ancestors, context.definition.id]);
  const children = context.definition.formulations[formulation]?.blocks ?? {};
  return { formulation, subblocks: Object.fromEntries(Object.entries(children).map(([alias, reference]) => {
    try { return [alias, defaultModel(resolveReference(reference, context.bindings ?? {}, registry), registry, undefined, next, budget)]; }
    catch { return [alias, { formulation: '', subblocks: {} }]; }
  })) };
}

export function parseModel(text, { allowIncomplete = false } = {}) {
  const catalog = JSON.parse(text);
  let count = 0;
  function check(selection, path, depth) {
    if (++count > 1500 || depth > 50) throw Error('Model exceeds 1500 model occurrences or 50 levels.');
    if (!isObject(selection) || Object.keys(selection).some(key => !['formulation', 'subblocks'].includes(key)))
      throw Error(`${path}: expected formulation and optional subblocks only. Select the root block separately.`);
    if (typeof selection.formulation !== 'string' || (!allowIncomplete && !selection.formulation)) throw Error(`${path}: missing formulation.`);
    if (selection.subblocks !== undefined && !isObject(selection.subblocks)) throw Error(`${path}: subblocks must be an object.`);
    return { formulation: selection.formulation, subblocks: Object.fromEntries(Object.entries(selection.subblocks ?? {}).map(([alias, child]) => [alias, check(child, `${path}.${alias}`, depth + 1)])) };
  }
  return check(catalog, 'root', 0);
}

// Declaration coverage, matching requirements.py: only the parent can supply a
// child's input. This does not compile equations, convert units or solve a model.
export function analyzeModel(context, catalog, registry) {
  const inputs = [], initial = [], occurrences = [], errors = [];
  let remaining = 1500;
  function visit(model, selection, path, supplied, depth) {
    const location = path.length ? path.join('.') : model.definition.id;
    if (--remaining < 0 || depth > 50) { errors.push(`${location}: model_document is too large or deeply nested.`); return; }
    if (model.unresolved) { errors.push(`${location}: unbound generic block. Choose a concrete root wrapper.`); return; }
    const formulation = model.definition.formulations[selection?.formulation];
    occurrences.push({ path, context: model, selection });
    if (!formulation) { errors.push(`${location}: choose a valid formulation.`); return; }
    const children = {};
    for (const [alias, reference] of Object.entries(formulation.blocks ?? {})) {
      try { children[alias] = resolveReference(reference, model.bindings ?? {}, registry); }
      catch (error) { errors.push(`${location}.${alias}: ${error.message}`); }
    }
    const expected = Object.keys(formulation.blocks ?? {}).sort();
    if (JSON.stringify(Object.keys(selection.subblocks ?? {}).sort()) !== JSON.stringify(expected))
      errors.push(`${location}: subblocks must be exactly ${expected.join(', ') || '(none)'}.`);
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
    for (const equation of Object.values(formulation.constraints ?? {})) register(equation.determines);
    for (const derivative of Object.values(formulation.derivatives ?? {})) {
      register(derivative.determines);
      const [struct, variable] = derivative.determines.split('.');
      const metadata = model.definition.structs[struct]?.variables[variable];
      if (metadata) initial.push({ path: [...path, struct, variable].join('.'), occurrence: path.join('.'), struct, name: variable, variable: metadata });
    }
    for (const connection of Object.values(formulation.connections ?? {})) {
      const parts = connection.to.split('.');
      const struct = parts.length === 1 ? model.definition.structs[parts[0]] : children[parts[0]]?.definition.structs[parts[1]];
      if (!struct) errors.push(`${location}: unknown connection target ${connection.to}.`);
      else for (const variable of Object.keys(struct.variables)) register(`${connection.to}.${variable}`);
    }
    if (formulation.external) for (const target of Object.keys(formulation.external.dependencies)) register(target);
    for (const output of outputs) if (!targets.has(output)) errors.push(`${location}: missing output determination ${output}.`);
    for (const [alias, child] of Object.entries(children)) {
      const prefix = `${alias}.`;
      const childSupplied = new Set([...targets].filter(target => target.startsWith(prefix)).map(target => target.slice(prefix.length)));
      visit(child, selection.subblocks?.[alias], [...path, alias], childSupplied, depth + 1);
    }
  }
  visit(context, catalog, [], new Set(), 0);
  return { inputs: inputs.sort((a, b) => a.path.localeCompare(b.path)), initial: initial.sort((a, b) => a.path.localeCompare(b.path)), occurrences, errors };
}
