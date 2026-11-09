import React, { useMemo, useState } from 'react';
import { plotGeometry, plotNumber, timeSeries } from './time-series.js';

export default function TimeSeriesChart({ variable, timeDimension, timeUnit }) {
  const groups = useMemo(() => timeSeries(variable, timeDimension), [variable, timeDimension]);
  const [chosen, setChosen] = useState('');
  const [cursor, setCursor] = useState(null);
  const group = groups.find(group => group.key === chosen) ?? groups[0];
  const points = group?.points ?? [];
  const geometry = useMemo(() => plotGeometry(points), [points]);
  if (!groups.length) return null;
  const selector = groups.length > 1 && <select aria-label={`Series for ${variable.variable_path}`} value={group.key} onChange={event => { setChosen(event.target.value); setCursor(null); }}>{groups.map(group => <option key={group.key} value={group.key}>{group.label}</option>)}</select>;
  if (!geometry) return <div className="time-series-chart">{selector}<p className="trajectory-unavailable">No finite saved values for this series.</p></div>;
  const point = points[Math.min(cursor ?? points.length - 1, points.length - 1)];
  function move(event) {
    const bounds = event.currentTarget.getBoundingClientRect();
    const x = (event.clientX - bounds.left) / bounds.width * geometry.width;
    let closest = 0;
    for (let index = 1; index < points.length; index++)
      if (Math.abs(geometry.x(points[index].time) - x) < Math.abs(geometry.x(points[closest].time) - x)) closest = index;
    setCursor(closest);
  }
  return <div className="time-series-chart">
    {selector}
    <div className="trajectory-caption"><span>Saved trajectory</span><code>{variable.unit}</code></div>
    <svg viewBox={`0 0 ${geometry.width} ${geometry.height}`} role="img" tabIndex="0" aria-label={`${variable.variable_path} versus ${timeDimension}, ${points.length} saved points. Use left and right arrows to inspect values.`}
      onPointerMove={move} onPointerLeave={() => setCursor(null)} onKeyDown={event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        setCursor(index => event.key === 'Home' ? 0 : event.key === 'End' ? points.length - 1 : Math.max(0, Math.min(points.length - 1, (index ?? points.length - 1) + (event.key === 'ArrowLeft' ? -1 : 1))));
      }}>
      <title>{`${variable.variable_path} (${variable.unit}) over ${timeDimension} (${timeUnit})`}</title>
      {[geometry.top, (geometry.top + geometry.bottom) / 2, geometry.bottom].map(y => <line key={y} x1={geometry.left} x2={geometry.right} y1={y} y2={y} className="trajectory-grid"/>)}
      <text x={geometry.left - 5} y={geometry.top + 4} textAnchor="end">{plotNumber(geometry.max)}</text>
      <text x={geometry.left - 5} y={geometry.bottom} textAnchor="end">{plotNumber(geometry.min)}</text>
      <path d={geometry.path} className="trajectory-line"/>
      {points.filter((point, index) => Number.isFinite(point.value) && !Number.isFinite(points[index - 1]?.value) && !Number.isFinite(points[index + 1]?.value)).map(point => <circle key={point.time} cx={geometry.x(point.time)} cy={geometry.y(point.value)} r="2" className="trajectory-point"/>)}
      <line x1={geometry.x(point.time)} x2={geometry.x(point.time)} y1={geometry.top} y2={geometry.bottom} className="trajectory-cursor"/>
      {Number.isFinite(point.value) && <circle cx={geometry.x(point.time)} cy={geometry.y(point.value)} r="3" className="trajectory-point"/>}
      <text x={geometry.left} y={geometry.height - 15}>{plotNumber(geometry.firstTime)}</text>
      <text x={geometry.right} y={geometry.height - 15} textAnchor="end">{plotNumber(geometry.lastTime)}</text>
      <text x={(geometry.left + geometry.right) / 2} y={geometry.height - 2} textAnchor="middle">{timeDimension} ({timeUnit})</text>
    </svg>
    <div className="trajectory-readout">{timeDimension}={plotNumber(point.time)} {timeUnit} · {Number.isFinite(point.value) ? `${plotNumber(point.value)} ${variable.unit}` : `Unavailable (${point.issue ?? 'unset'})`} · {point.fixed ? 'Fixed' : 'Free'}</div>
  </div>;
}
