import { parseFeeds } from './feeds.js';
import { parseModel } from './model_selection.js';
import { parseResources } from './resources.js';
import { parseResults, sameModel } from './results.js';

export function parseWorkspace(text) {
  const value = JSON.parse(text);
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      !['model_catalog,resources,results', 'feeds,model_catalog,resources,results'].includes(Object.keys(value).sort().join(',')))
    throw Error('A workspace contains model_catalog, resources, results and optionally feeds.');
  const model_catalog = parseModel(JSON.stringify(value.model_catalog));
  const resources = parseResources(JSON.stringify(value.resources));
  const results = parseResults(JSON.stringify(value.results));
  if (!sameModel(model_catalog, results.model_catalog))
    throw Error('Workspace model_catalog must match its results snapshot.');
  return { model_catalog, resources, results, ...(value.feeds != null ? { feeds: parseFeeds(JSON.stringify(value.feeds)) } : {}) };
}
