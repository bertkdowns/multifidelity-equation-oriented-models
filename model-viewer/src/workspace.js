import { parseImplementation } from './implementation.js';
import { parseInformation } from './information.js';
import { parseResults, sameImplementation } from './results.js';

export function parseWorkspace(text) {
  const value = JSON.parse(text);
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      Object.keys(value).sort().join(',') !== 'implementation,information,results')
    throw Error('A workspace contains exactly implementation, information and results.');
  const implementation = parseImplementation(JSON.stringify(value.implementation));
  const information = parseInformation(JSON.stringify(value.information));
  const results = parseResults(JSON.stringify(value.results));
  if (!sameImplementation(implementation, results.implementation))
    throw Error('Workspace implementation must match its results snapshot.');
  return { implementation, information, results };
}
