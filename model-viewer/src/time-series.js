export function timeDomainsByOccurrence(analysis) {
  return new Map((analysis?.occurrences ?? []).map(occurrence => [occurrence.path.join('.'),
    Object.entries(occurrence.context.definition.domains ?? {}).filter(([, domain]) => domain.kind === 'time').map(([name]) => name)]));
}

export function timeDimensionForVariable(variable, domains) {
  const occurrence = variable.variable_path.split('.').slice(0, -2).join('.');
  return (domains.get(occurrence) ?? []).find(name => variable.dimensions.includes(name));
}

export const plotNumber = number => Number(number.toPrecision(5)).toString();

export function timeSeries(variable, dimension) {
  const axis = variable.dimensions.indexOf(dimension);
  if (axis < 0) return [];
  const groups = new Map();
  for (const entry of variable.entries) {
    const time = entry.index[axis];
    if (typeof time !== 'number' || !Number.isFinite(time)) continue;
    const coordinates = entry.index.filter((_, index) => index !== axis);
    const key = JSON.stringify(coordinates);
    if (!groups.has(key)) groups.set(key, { key, label: variable.dimensions.filter((_, index) => index !== axis)
      .map((name, index) => `${name}=${JSON.stringify(coordinates[index])}`).join(', ') || 'All time points', points: [] });
    groups.get(key).points.push({ time, value: entry.value, issue: entry.issue, fixed: entry.fixed });
  }
  return [...groups.values()].map(group => ({ ...group, points: group.points.sort((a, b) => a.time - b.time) }));
}

export function plotGeometry(points, width = 250, height = 136) {
  if (!points.length) return null;
  const values = points.filter(point => Number.isFinite(point.value)).map(point => point.value);
  if (!values.length) return null;
  const left = 49, right = width - 9, top = 12, bottom = height - 29;
  let minTime = points[0].time, maxTime = points.at(-1).time;
  const firstTime = minTime, lastTime = maxTime;
  if (minTime === maxTime) { minTime -= 0.5; maxTime += 0.5; }
  let min = values[0], max = values[0];
  for (const value of values) { min = Math.min(min, value); max = Math.max(max, value); }
  const pad = max === min ? Math.max(Math.abs(min) * 0.05, 0.5) : (max - min) * 0.08;
  min -= pad; max += pad;
  const x = time => left + (time - minTime) / (maxTime - minTime) * (right - left);
  const y = value => bottom - (value - min) / (max - min) * (bottom - top);
  let penDown = false;
  const path = points.map(point => {
    if (!Number.isFinite(point.value)) { penDown = false; return ''; }
    const command = `${penDown ? 'L' : 'M'}${x(point.time)},${y(point.value)}`;
    penDown = true; return command;
  }).join(' ');
  return { width, height, left, right, top, bottom, min, max, firstTime, lastTime, path, x, y };
}
