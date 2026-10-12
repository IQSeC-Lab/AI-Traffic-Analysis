"use client";

import { useMemo, useState } from "react";

import { Tooltip } from "./ChartCard";
import { MARGIN, columnPath, linear, niceTicks, useWidth, type Series } from "./scale";

type ColumnSeries = Series & { values: (number | null)[]; spreads?: (number | null)[] };

const truncate = (text: string, max: number) => (text.length > max ? `${text.slice(0, max - 1)}…` : text);

/**
 * One column per series in each category; columns are at most 24px with 2px gaps.
 * `spreads` draws a whisker of plus and minus that much on each column, `reference` a dashed
 * line across the plot (a chance level), and `max` fixes the top of the axis (100%).
 */
export function GroupedColumns({
  categories,
  shortLabels,
  series,
  format,
  height = 240,
  ariaLabel,
  reference,
  max,
}: {
  categories: string[];
  shortLabels?: string[];
  series: ColumnSeries[];
  format: (v: number) => string;
  height?: number;
  ariaLabel: string;
  reference?: { value: number; label: string };
  max?: number;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  const layout = useMemo(() => {
    if (!width || categories.length === 0) return null;
    const plotRight = width - MARGIN.right;
    const plotBottom = height - MARGIN.bottom;
    const band = (plotRight - MARGIN.left) / categories.length;
    const barW = Math.max(4, Math.min(24, (band * 0.7 - (series.length - 1) * 2) / series.length));
    const groupW = barW * series.length + (series.length - 1) * 2;
    const maxValue = Math.max(0, reference?.value ?? 0, ...series.flatMap((s) => s.values.map((v, i) => (v ?? 0) + (s.spreads?.[i] ?? 0))));
    const yTicks = max != null ? niceTicks(0, max, 4).filter((t) => t <= max) : niceTicks(0, maxValue || 1, 4);
    const top = max ?? yTicks[yTicks.length - 1];
    const y = (v: number) => linear([0, top], [plotBottom, MARGIN.top])(Math.min(top, Math.max(0, v)));
    const bandStart = (i: number) => MARGIN.left + i * band;
    return { plotRight, plotBottom, band, barW, groupW, y, yTicks, bandStart };
  }, [width, height, categories.length, series, reference?.value, max]);

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
                  const v = s.values[i];
                  if (v == null) return null;
                  const top = layout.y(v);
                  const spread = s.spreads?.[i];
                  const center = start + j * (layout.barW + 2) + layout.barW / 2;
                  const cap = Math.min(5, layout.barW / 2);
                  return (
                    <g key={s.id}>
                      <path d={columnPath(start + j * (layout.barW + 2), top, layout.barW, layout.plotBottom - top)} fill={s.color} />
                      {spread != null && spread > 0 && (
                        <path
                          d={`M${center},${layout.y(v - spread)}V${layout.y(v + spread)}M${center - cap},${layout.y(v + spread)}h${2 * cap}M${center - cap},${layout.y(v - spread)}h${2 * cap}`}
                          stroke="var(--ink)"
                          strokeWidth={1.5}
                          fill="none"
                        />
                      )}
                    </g>
                  );
                })}
                <text
                  x={layout.bandStart(i) + layout.band / 2}
                  y={layout.plotBottom + 18}
                  textAnchor="middle"
                  className="fill-ink-3 text-[11px]"
                >
                  {truncate(shortLabels?.[i] ?? c, Math.max(4, Math.floor(layout.band / 6.5)))}
                </text>
              </g>
            );
          })}
          {reference && (
            <g pointerEvents="none">
              <line x1={MARGIN.left} x2={layout.plotRight} y1={layout.y(reference.value)} y2={layout.y(reference.value)} stroke="var(--ink-3)" strokeDasharray="4 3" />
              {/* At the left edge: the columns sit in the middle of their bands, so nothing is drawn there */}
              <text x={MARGIN.left + 4} y={layout.y(reference.value) - 5} className="fill-ink-3 text-[11px]">
                {reference.label}
              </text>
            </g>
          )}
          <line x1={MARGIN.left} x2={layout.plotRight} y1={layout.plotBottom} y2={layout.plotBottom} stroke="var(--axis)" />
        </svg>
      )}
      {layout && hover !== null && (
        <Tooltip
          x={layout.bandStart(hover) + layout.band / 2}
          y={MARGIN.top}
          width={width}
          title={categories[hover]}
          rows={series.map((s) => ({
            color: series.length > 1 ? s.color : undefined,
            label: s.label,
            value:
              s.values[hover] == null
                ? "—"
                : format(s.values[hover] as number) + (s.spreads?.[hover] != null ? ` ± ${format(s.spreads[hover] as number)}` : ""),
          }))}
        />
      )}
    </div>
  );
}
