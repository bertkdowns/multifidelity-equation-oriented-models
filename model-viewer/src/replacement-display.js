// Replacement annotations come from saved specifications, never quantity names.
export function replacementPairs(specification, records) {
  const byId = new Map(records.map(record => [record.id, record]));
  const pairs = [], warnings = [];
  for (const [recordId, to] of Object.entries(specification?.replacements ?? {})) {
    const record = byId.get(recordId);
    if (!record) {
      warnings.push(`Replacement ${recordId}: load its information record to trace the fixed variable.`);
      continue;
    }
    pairs.push({ recordId, from: record.variable_path, to });
  }
  return { pairs, warnings };
}

export function displayedValues(records, result, selectedIds = new Set()) {
  const record = records.find(record => selectedIds.has(record.id)) ?? records[0];
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
