import { useEffect, useRef, useState } from 'react';
import { Table } from 'lucide-react';
import { clamp, formatDateTime, formatHour } from '../lib/format.js';

const HEIGHT = 220;
const MARGIN = { top: 22, right: 12, bottom: 26, left: 34 };
const MAX_BAR_WIDTH = 24;
const BAR_GAP = 2;
const BAR_RADIUS = 4;

/** Largest "nice" axis maximum and step (1/2/5 x 10^k) giving at most four integer ticks. */
function niceScale(maxValue) {
  const target = Math.max(4, maxValue);
  const rough = target / 4;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 5, 10].map((factor) => factor * magnitude).find((candidate) => candidate >= rough);
  const wholeStep = Math.max(1, Math.round(step));
  return { step: wholeStep, max: Math.ceil(target / wholeStep) * wholeStep };
}

/** Column with a rounded data-end and a square foot on the baseline. */
function columnPath(x, y, width, height) {
  const radius = Math.min(BAR_RADIUS, width / 2, height);
  const bottom = y + height;
  return [
    `M${x},${bottom}`,
    `V${y + radius}`,
    `Q${x},${y} ${x + radius},${y}`,
    `H${x + width - radius}`,
    `Q${x + width},${y} ${x + width},${y + radius}`,
    `V${bottom}`,
    'Z',
  ].join(' ');
}

function useMeasuredWidth() {
  const ref = useRef(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const node = ref.current;
    if (!node) return undefined;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

function countLabel(count) {
  return `${count} incident${count === 1 ? '' : 's'}`;
}

function HourTable({ hours }) {
  return (
    <div className="chart-table-wrap">
      <table className="chart-table">
        <caption className="sr-only">Incidents per hour</caption>
        <thead>
          <tr>
            <th scope="col">Hour starting</th>
            <th scope="col">Incidents</th>
          </tr>
        </thead>
        <tbody>
          {hours.map((entry) => (
            <tr key={entry.hour}>
              <td>{formatDateTime(entry.hour)}</td>
              <td>{entry.count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Incidents per hour as a single-series column chart (inline SVG, no chart library).
 *
 * Form: counts in time buckets -> columns. One series -> one colour and no legend (the
 * title names it). Only the peak is direct-labelled; everything else is readable from the
 * axis, the hover/focus tooltip and the table view, so no value is gated behind hover.
 * Keyboard: focus the plot, then Left/Right/Home/End walk the hours.
 *
 * @param {{stats: {by_hour: {hour: string, count: number}[], hours: number} | null, loading: boolean}} props
 */
export default function StatsChart({ stats, loading }) {
  const [containerRef, width] = useMeasuredWidth();
  const [activeIndex, setActiveIndex] = useState(null);
  const [showTable, setShowTable] = useState(false);

  const hours = Array.isArray(stats?.by_hour) ? stats.by_hour : [];
  const counts = hours.map((entry) => Number(entry.count) || 0);
  const peak = Math.max(0, ...counts);
  const peakIndex = peak > 0 ? counts.indexOf(peak) : -1;
  const scale = niceScale(peak);

  const plotWidth = Math.max(0, width - MARGIN.left - MARGIN.right);
  const plotHeight = HEIGHT - MARGIN.top - MARGIN.bottom;
  const band = hours.length > 0 ? plotWidth / hours.length : 0;
  const barWidth = clamp(band - BAR_GAP, 1, MAX_BAR_WIDTH);
  const baseline = MARGIN.top + plotHeight;
  const yFor = (value) => baseline - (value / scale.max) * plotHeight;
  const xFor = (index) => MARGIN.left + index * band + (band - barWidth) / 2;

  // Thin the x labels to what fits: roughly one label per 56 px.
  const labelEvery = band > 0 ? Math.max(1, Math.ceil(56 / band)) : 1;
  const ticks = [];
  for (let value = 0; value <= scale.max; value += scale.step) ticks.push(value);

  const active = activeIndex !== null && activeIndex < hours.length ? activeIndex : null;

  const onKeyDown = (event) => {
    if (hours.length === 0) return;
    const last = hours.length - 1;
    let next = null;
    if (event.key === 'ArrowRight') next = active === null ? 0 : Math.min(last, active + 1);
    else if (event.key === 'ArrowLeft') next = active === null ? last : Math.max(0, active - 1);
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = last;
    else if (event.key === 'Escape') setActiveIndex(null);
    if (next === null) return;
    event.preventDefault();
    setActiveIndex(next);
  };

  const tooltipLeft = active === null ? 0 : clamp(xFor(active) + barWidth / 2, 70, Math.max(70, width - 70));

  return (
    <figure className="chart">
      <div className="chart-toolbar">
        <figcaption>
          {hours.length > 0 ? `${countLabel(stats.total ?? 0)} in the last ${stats.hours ?? hours.length} h, by hour (local time)` : 'Waiting for statistics'}
        </figcaption>
        <button type="button" className="btn ghost small" aria-pressed={showTable} onClick={() => setShowTable((value) => !value)}>
          <Table size={14} aria-hidden="true" />
          {showTable ? 'Show chart' : 'Show table'}
        </button>
      </div>

      {showTable ? (
        <HourTable hours={hours} />
      ) : (
        <div
          ref={containerRef}
          className={loading ? 'chart-plot refreshing' : 'chart-plot'}
          tabIndex={0}
          role="group"
          aria-label="Incidents per hour column chart. Use the left and right arrow keys to read each hour."
          onKeyDown={onKeyDown}
          onBlur={() => setActiveIndex(null)}
          onPointerLeave={() => setActiveIndex(null)}
        >
          {width > 0 && (
            <svg width={width} height={HEIGHT} role="presentation">
              {ticks.map((value) => (
                <g key={value}>
                  <line className={value === 0 ? 'chart-axis' : 'chart-grid'} x1={MARGIN.left} x2={width - MARGIN.right} y1={yFor(value)} y2={yFor(value)} />
                  <text className="chart-tick" x={MARGIN.left - 8} y={yFor(value)} textAnchor="end" dominantBaseline="middle">
                    {value.toLocaleString()}
                  </text>
                </g>
              ))}

              {hours.map((entry, index) => {
                const count = counts[index];
                const height = (count / scale.max) * plotHeight;
                return (
                  <g key={entry.hour}>
                    {count > 0 && (
                      <path
                        className={index === active ? 'chart-bar active' : 'chart-bar'}
                        d={columnPath(xFor(index), baseline - height, barWidth, height)}
                      />
                    )}
                    {index === peakIndex && (
                      <text className="chart-value" x={xFor(index) + barWidth / 2} y={baseline - height - 6} textAnchor="middle">
                        {count.toLocaleString()}
                      </text>
                    )}
                    {index % labelEvery === 0 && (
                      <text className="chart-tick" x={xFor(index) + barWidth / 2} y={baseline + 16} textAnchor="middle">
                        {formatHour(entry.hour)}
                      </text>
                    )}
                    {/* Full-height, full-band hit target: the pointer only has to be in the hour's column. */}
                    <rect
                      className="chart-hit"
                      x={MARGIN.left + index * band}
                      y={MARGIN.top}
                      width={band}
                      height={plotHeight}
                      onPointerEnter={() => setActiveIndex(index)}
                      onPointerDown={() => setActiveIndex(index)}
                    />
                  </g>
                );
              })}
            </svg>
          )}

          {hours.length > 0 && peak === 0 && <p className="chart-empty">No incidents in this window</p>}

          {active !== null && (
            <div className="chart-tooltip" role="status" style={{ left: tooltipLeft, top: Math.max(0, yFor(counts[active]) - 50) }}>
              <strong>{countLabel(counts[active])}</strong>
              <span>{formatDateTime(hours[active].hour)}</span>
            </div>
          )}
        </div>
      )}
    </figure>
  );
}
