// Replacement annotations come from saved parameters, never quantity names.
export function replacementPairs(parameters, records) {
  const byTag = new Map(records.map(record => [record.tag, record]));
  const pairs = [], warnings = [];
  for (const [recordTag, to] of Object.entries(parameters?.replacements ?? {})) {
    const record = byTag.get(recordTag);
    if (!record) {
      warnings.push(`Replacement ${recordTag}: load its resource record to trace the fixed variable.`);
      continue;
    }
    pairs.push({ recordTag, from: record.variable_path, to });
  }
  return { pairs, warnings };
}

export function displayedValues(records, result, selectedTags = new Set()) {
  const record = records.find(record => selectedTags.has(record.tag)) ?? records[0];
  return { record, result: record ? undefined : result };
}

export function replacementCell(variable, pairs, canonicalPaths, initialPaths = new Set()) {
  if (!variable.entries.some(entry => entry.fixed)) return '—';
  const pair = pairs.find(pair => pair.from === variable.variable_path);
  if (pair) return pair.to;
  if (canonicalPaths.has(variable.variable_path)) return 'Direct input';
  if (initialPaths.has(variable.variable_path)) return 'Initial condition';
  return 'Not recorded';
}
