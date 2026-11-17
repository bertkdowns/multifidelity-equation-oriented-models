import { parseFeeds } from './feeds.js';
import { parseModel } from './model_selection.js';
import { parseResources } from './resources.js';
import { parseResults, sameModel } from './results.js';

export function parseWorkspace(text) {
  const value = JSON.parse(text);
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      !['model_document,resources,results', 'feeds,model_document,resources,results'].includes(Object.keys(value).sort().join(',')))
    throw Error('A workspace contains model_document, resources, results and optionally feeds.');
  const model_document = parseModel(JSON.stringify(value.model_document));
  const resources = parseResources(JSON.stringify(value.resources));
  const results = parseResults(JSON.stringify(value.results));
  if (!sameModel(model_document, results.model_document))
    throw Error('Workspace model_document must match its results snapshot.');
  return { model_document, resources, results, ...(value.feeds != null ? { feeds: parseFeeds(JSON.stringify(value.feeds)) } : {}) };
}
