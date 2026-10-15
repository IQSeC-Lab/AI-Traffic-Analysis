"use client";

import { useMemo, useState } from "react";

import { Tooltip } from "./ChartCard";
import { MARGIN, linear, logScale, logTicks, niceTicks, useWidth, type Series } from "./scale";

/** Quartiles of a group, with whiskers at the furthest values within 1.5 times the box's height of it. */
export type Box = { low: number; q1: number; median: number; q3: number; high: number; n: number };

function quantile(sorted: number[], q: number) {
  const at = (sorted.length - 1) * q;
  const below = Math.floor(at);
  return sorted[below] + (sorted[Math.min(sorted.length - 1, below + 1)] - sorted[below]) * (at - below);
}

export function boxOf(values: number[]): Box | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const q1 = quantile(sorted, 0.25);
  const q3 = quantile(sorted, 0.75);
  const reach = 1.5 * (q3 - q1);
  return {
    low: sorted.find((v) => v >= q1 - reach) ?? sorted[0],
    q1,
    median: quantile(sorted, 0.5),
    q3,
    high: [...sorted].reverse().find((v) => v <= q3 + reach) ?? sorted[sorted.length - 1],
    n: sorted.length,
  };
}

type BoxSeries = Series & { boxes: (Box | null)[] };

const truncate = (text: string, max: number) => (text.length > max ? `${text.slice(0, max - 1)}…` : text);

/** One box per series in each category: the middle half of its values, the median across it, whiskers to the rest. */
export function BoxPlot({
  categories,
  shortLabels,
  series,
  format,
  log = false,
  ticks,
  height = 240,
  ariaLabel,
}: {
  categories: string[];
  shortLabels?: string[];
  series: BoxSeries[];
  format: (v: number) => string;
  log?: boolean;
  /** The log axis's tick values, lowest first, when powers of ten don't read well in the unit shown (bytes). */
  ticks?: number[];
  height?: number;
  ariaLabel: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  const layout = useMemo(() => {
    const boxes = series.flatMap((s) => s.boxes).filter((b): b is Box => b != null);
    if (!width || categories.length === 0 || boxes.length === 0) return null;
    const plotRight = width - MARGIN.right;
    const plotBottom = height - MARGIN.bottom;
    const band = (plotRight - MARGIN.left) / categories.length;
    const boxW = Math.max(6, Math.min(24, (band * 0.7 - (series.length - 1) * 4) / series.length));
    const groupW = boxW * series.length + (series.length - 1) * 4;
    const lowest = Math.min(...boxes.map((b) => b.low));
    const highest = Math.max(...boxes.map((b) => b.high));
    // A log axis needs positive values; a measurement that can be zero falls back to a linear one
    const useLog = log && lowest > 0 && highest > lowest;
    let yTicks: number[];
    let y: (v: number) => number;
    if (useLog) {
      const below = ticks?.filter((t) => t <= lowest).pop();
      const above = ticks?.find((t) => t >= highest);
      const domain: [number, number] = [below ?? 10 ** Math.floor(Math.log10(lowest)), above ?? 10 ** Math.ceil(Math.log10(highest))];
      yTicks = below && above ? ticks!.filter((t) => t >= below && t <= above) : logTicks(domain[0], domain[1]);
      y = logScale(domain, [plotBottom, MARGIN.top]);
    } else {
      yTicks = niceTicks(0, highest || 1, 4);
      y = linear([0, yTicks[yTicks.length - 1]], [plotBottom, MARGIN.top]);
    }
    return { plotRight, plotBottom, band, boxW, groupW, y, yTicks, bandStart: (i: number) => MARGIN.left + i * band };
  }, [width, height, categories.length, series, log, ticks]);

  return (
    <div ref={ref} className="relative" style={{ height }}>
      {layout && (
        <svg width={width} height={height} role="img" aria-label={ariaLabel} className="block" onPointerLeave={() => setHover(null)}>
          {layout.yTicks.map((t) => (
            <g key={t}>
              <line x1={MARGIN.left} x2={layout.plotRight} y1={layout.y(t)} y2={layout.y(t)} stroke="var(--hairline)" />
              <text x={MARGIN.left - 8} y={layout.y(t)} dy="0.32em" textAnchor="end" className="fill-ink-3 text-[11px] tabular-nums">
                {format(t)}
              </text>
            </g>
          ))}
          {categories.map((c, i) => {
            const start = layout.bandStart(i) + (layout.band - layout.groupW) / 2;
            return (
              <g key={c} onPointerEnter={() => setHover(i)}>
                <rect x={layout.bandStart(i)} y={MARGIN.top} width={layout.band} height={layout.plotBottom - MARGIN.top} fill={hover === i ? "var(--surface-2)" : "transparent"} />
                {series.map((s, j) => {
                  const b = s.boxes[i];
                  if (!b) return null;
                  const x = start + j * (layout.boxW + 4);
                  const center = x + layout.boxW / 2;
                  const cap = layout.boxW / 4;
                  const top = layout.y(b.q3);
                  return (
                    <g key={s.id}>
                      <path
                        d={`M${center},${layout.y(b.low)}V${layout.y(b.high)}M${center - cap},${layout.y(b.low)}h${2 * cap}M${center - cap},${layout.y(b.high)}h${2 * cap}`}
                        stroke={s.color}
                        strokeWidth={1.5}
                        fill="none"
                      />
                      <rect x={x} y={top} width={layout.boxW} height={Math.max(2, layout.y(b.q1) - top)} rx={2} fill={s.color} />
                      <line x1={x} x2={x + layout.boxW} y1={layout.y(b.median)} y2={layout.y(b.median)} stroke="var(--surface)" strokeWidth={2} />
                    </g>
                  );
                })}
                <text x={layout.bandStart(i) + layout.band / 2} y={layout.plotBottom + 18} textAnchor="middle" className="fill-ink-3 text-[11px]">
                  {truncate(shortLabels?.[i] ?? c, Math.max(4, Math.floor(layout.band / 6.5)))}
                </text>
              </g>
            );
          })}
          <line x1={MARGIN.left} x2={layout.plotRight} y1={layout.plotBottom} y2={layout.plotBottom} stroke="var(--axis)" />
        </svg>
      )}
      {layout && hover !== null && (
        <Tooltip
          x={layout.bandStart(hover) + layout.band / 2}
          y={MARGIN.top}
          width={width}
          title={categories[hover]}
          rows={series.map((s) => {
            const b = s.boxes[hover];
            return {
              color: series.length > 1 ? s.color : undefined,
              label: b ? `${s.label} · half between ${format(b.q1)} and ${format(b.q3)}` : s.label,
              value: b ? format(b.median) : "—",
            };
          })}
        />
      )}
    </div>
  );
}
