import { parseImplementation } from './implementation.js';
import { parseInformation } from './information.js';
import { parseResults } from './results.js';

const prefix = kind => `multifidelity:document:v1:${kind}:`;
export const documentKey = (kind, root) => prefix(kind) + encodeURIComponent(root);
const activeModelKey = 'multifidelity:active-model:v1';
export function loadActiveModel(library, fallback, storage) {
  try {
    const root = (storage ?? globalThis.localStorage).getItem(activeModelKey);
    return Object.hasOwn(library, root) ? root : fallback;
  } catch { return fallback; }
}
export function saveActiveModel(root, storage) {
  try { (storage ?? globalThis.localStorage).setItem(activeModelKey, root); }
  catch { /* Document hooks report unavailable storage separately. */ }
}

function validate(kind, value, root) {
  if (kind === 'implementation') return parseImplementation(JSON.stringify(value), { allowIncomplete: true });
  if (!value || typeof value.name !== 'string') throw Error('Missing filename.');
  if (kind === 'information') return { name: value.name, records: parseInformation(JSON.stringify(value.records)) };
  if (kind === 'results') {
    const document = parseResults(JSON.stringify(value.document));
    if (document.model_id !== root) throw Error('Results belong to another model.');
    return { name: value.name, document };
  }
  throw Error('Unknown document kind.');
}

export function loadDocuments(kind, storage) {
  const documents = {}, errors = [];
  try {
    storage ??= globalThis.localStorage;
    for (let index = 0; index < storage.length; index++) {
      const key = storage.key(index);
      if (!key?.startsWith(prefix(kind))) continue;
      try {
        const root = decodeURIComponent(key.slice(prefix(kind).length));
        documents[root] = validate(kind, JSON.parse(storage.getItem(key)), root);
      } catch { errors.push(`Saved ${kind} document could not be restored (${key.slice(prefix(kind).length)}).`); }
    }
  } catch { errors.push(`Browser storage is unavailable; ${kind} documents will only be kept for this session.`); }
  return { documents, errors };
}

export function persistDocuments(kind, documents, previous, storage) {
  const saved = { ...previous }, errors = [];
  for (const [root, document] of Object.entries(documents)) {
    if (previous[root] === document) continue;
    try {
      storage ??= globalThis.localStorage;
      const key = documentKey(kind, root);
      if (document == null) storage.removeItem(key);
      else storage.setItem(key, JSON.stringify(document));
      saved[root] = document;
    } catch { errors.push(`Could not save ${kind} for ${root}. Browser storage may be full or disabled; download the JSON to keep it.`); }
  }
  return { saved, errors };
}
