"use client";

import { useMemo, useState } from "react";

import { Tooltip } from "./ChartCard";
import { MARGIN, columnPath, linear, niceTicks, useWidth, type Series } from "./scale";

type ColumnSeries = Series & { values: (number | null)[] };

const truncate = (text: string, max: number) => (text.length > max ? `${text.slice(0, max - 1)}…` : text);

/** One column per series in each category; columns are at most 24px with 2px gaps. */
export function GroupedColumns({
  categories,
  shortLabels,
  series,
  format,
  height = 240,
  ariaLabel,
}: {
  categories: string[];
  shortLabels?: string[];
  series: ColumnSeries[];
  format: (v: number) => string;
  height?: number;
  ariaLabel: string;
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
    const maxValue = Math.max(0, ...series.flatMap((s) => s.values.map((v) => v ?? 0)));
    const yTicks = niceTicks(0, maxValue || 1, 4);
    const y = linear([0, yTicks[yTicks.length - 1]], [plotBottom, MARGIN.top]);
    const bandStart = (i: number) => MARGIN.left + i * band;
    return { plotRight, plotBottom, band, barW, groupW, y, yTicks, bandStart };
  }, [width, height, categories.length, series]);

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
                  return (
                    <path
                      key={s.id}
                      d={columnPath(start + j * (layout.barW + 2), top, layout.barW, layout.plotBottom - top)}
                      fill={s.color}
                    />
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
            value: s.values[hover] == null ? "—" : format(s.values[hover] as number),
          }))}
        />
      )}
    </div>
  );
}
