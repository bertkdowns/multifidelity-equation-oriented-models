import { parseFeeds } from './feeds.js';
import { parseModel } from './model_selection.js';
import { parseResources } from './resources.js';
import { parseResults } from './results.js';

const prefix = kind => `multifidelity:catalog:v1:${kind}:`;
export const catalogKey = (kind, root) => prefix(kind) + encodeURIComponent(root);
const activeBlockKey = 'multifidelity:active-block:v1';
export function loadActiveBlock(library, fallback, storage) {
  try {
    const root = (storage ?? globalThis.localStorage).getItem(activeBlockKey);
    return Object.hasOwn(library, root) ? root : fallback;
  } catch { return fallback; }
}
export function saveActiveBlock(root, storage) {
  try { (storage ?? globalThis.localStorage).setItem(activeBlockKey, root); }
  catch { /* Catalog hooks report unavailable storage separately. */ }
}

function validate(kind, value, root) {
  if (kind === 'model_catalog') return parseModel(JSON.stringify(value), { allowIncomplete: true });
  if (!value || typeof value.name !== 'string') throw Error('Missing filename.');
  if (kind === 'feeds') return { name: value.name, feeds: parseFeeds(JSON.stringify(value.feeds)) };
  if (kind === 'resources') return { name: value.name, records: parseResources(JSON.stringify(value.records)) };
  if (kind === 'results') {
    const catalog = parseResults(JSON.stringify(value.catalog));
    if (catalog.block_id !== root) throw Error('Results belong to another model.');
    return { name: value.name, catalog };
  }
  throw Error('Unknown catalog kind.');
}

export function loadCatalogs(kind, storage) {
  const catalogs = {}, errors = [];
  try {
    storage ??= globalThis.localStorage;
    for (let index = 0; index < storage.length; index++) {
      const key = storage.key(index);
      if (!key?.startsWith(prefix(kind))) continue;
      try {
        const root = decodeURIComponent(key.slice(prefix(kind).length));
        catalogs[root] = validate(kind, JSON.parse(storage.getItem(key)), root);
      } catch { errors.push(`Saved ${kind} catalog could not be restored (${key.slice(prefix(kind).length)}).`); }
    }
  } catch { errors.push(`Browser storage is unavailable; ${kind} catalogs will only be kept for this session.`); }
  return { catalogs, errors };
}

export function persistCatalogs(kind, catalogs, previous, storage) {
  const saved = { ...previous }, errors = [];
  for (const [root, catalog] of Object.entries(catalogs)) {
    if (previous[root] === catalog) continue;
    try {
      storage ??= globalThis.localStorage;
      const key = catalogKey(kind, root);
      if (catalog == null) storage.removeItem(key);
      else storage.setItem(key, JSON.stringify(catalog));
      saved[root] = catalog;
    } catch { errors.push(`Could not save ${kind} for ${root}. Browser storage may be full or disabled; download the JSON to keep it.`); }
  }
  return { saved, errors };
}
