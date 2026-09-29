"use client";

import { useMemo, useState } from "react";

import { Tooltip } from "./ChartCard";
import { MARGIN, columnPath, linear, logScale, logTicks, niceTicks, useWidth, type Series } from "./scale";

type HistogramSeries = Series & { values: number[] };

/**
 * Distribution over shared bins. One series draws columns; several draw
 * 2px lines through the bin centers so the shapes can be compared.
 */
export function Histogram({
  edges,
  series,
  log = false,
  formatX,
  formatY,
  height = 240,
  ariaLabel,
}: {
  edges: number[];
  series: HistogramSeries[];
  log?: boolean;
  formatX: (v: number) => string;
  formatY: (v: number) => string;
  height?: number;
  ariaLabel: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const bins = Math.max(0, edges.length - 1);

  const layout = useMemo(() => {
    if (!width || bins === 0) return null;
    const plotRight = width - MARGIN.right;
    const plotBottom = height - MARGIN.bottom;
    const domain: [number, number] = [edges[0], edges[bins]];
    const x = log ? logScale(domain, [MARGIN.left, plotRight]) : linear(domain, [MARGIN.left, plotRight]);
    const maxValue = Math.max(0, ...series.flatMap((s) => s.values));
    const yTicks = niceTicks(0, maxValue || 1, 4);
    const y = linear([0, yTicks[yTicks.length - 1]], [plotBottom, MARGIN.top]);
    const xTicks = log ? logTicks(domain[0], domain[1]) : niceTicks(domain[0], domain[1], 6).filter((t) => t >= domain[0] && t <= domain[1]);
    const center = (i: number) => (x(edges[i]) + x(edges[i + 1])) / 2;
    return { x, y, yTicks, xTicks, plotRight, plotBottom, center };
  }, [width, height, edges, bins, series, log]);

  const single = series.length === 1;

  function onMove(e: React.PointerEvent<SVGSVGElement>) {
    if (!layout) return;
    const px = e.clientX - e.currentTarget.getBoundingClientRect().left;
    let best = 0;
    for (let i = 1; i < bins; i++) {
      if (Math.abs(layout.center(i) - px) < Math.abs(layout.center(best) - px)) best = i;
    }
    setHover(px >= MARGIN.left - 8 && px <= layout.plotRight + 8 ? best : null);
  }

  return (
    <div ref={ref} className="relative" style={{ height }}>
      {layout && (
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={ariaLabel}
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
          className="block touch-none"
        >
          {layout.yTicks.map((t) => (
            <g key={t}>
              <line x1={MARGIN.left} x2={layout.plotRight} y1={layout.y(t)} y2={layout.y(t)} stroke="var(--hairline)" />
              <text x={MARGIN.left - 8} y={layout.y(t)} dy="0.32em" textAnchor="end" className="fill-ink-3 text-[11px] tabular-nums">
                {formatY(t)}
              </text>
            </g>
          ))}
          {layout.xTicks.map((t) => (
            <text key={t} x={layout.x(t)} y={layout.plotBottom + 18} textAnchor="middle" className="fill-ink-3 text-[11px] tabular-nums">
              {formatX(t)}
            </text>
          ))}

          {single
            ? series[0].values.map((v, i) => {
                const x0 = layout.x(edges[i]);
                const x1 = layout.x(edges[i + 1]);
                const w = Math.min(24, Math.max(1, x1 - x0 - 2));
                const top = layout.y(v);
                return (
                  <path
                    key={i}
                    d={columnPath((x0 + x1) / 2 - w / 2, top, w, layout.plotBottom - top)}
                    fill={series[0].color}
                    opacity={hover === null || hover === i ? 1 : 0.55}
                  />
                );
              })
            : series.map((s) => (
                <polyline
                  key={s.id}
                  points={s.values.map((v, i) => `${layout.center(i)},${layout.y(v)}`).join(" ")}
                  fill="none"
                  stroke={s.color}
                  strokeWidth={2}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
              ))}

          <line x1={MARGIN.left} x2={layout.plotRight} y1={layout.plotBottom} y2={layout.plotBottom} stroke="var(--axis)" />

          {hover !== null && !single && (
            <g>
              <line
                x1={layout.center(hover)}
                x2={layout.center(hover)}
                y1={MARGIN.top}
                y2={layout.plotBottom}
                stroke="var(--axis)"
              />
              {series.map((s) => (
                <circle
                  key={s.id}
                  cx={layout.center(hover)}
                  cy={layout.y(s.values[hover])}
                  r={4}
                  fill={s.color}
                  stroke="var(--surface)"
                  strokeWidth={2}
                />
              ))}
            </g>
          )}
        </svg>
      )}
      {layout && hover !== null && (
        <Tooltip
          x={layout.center(hover)}
          y={MARGIN.top}
          width={width}
          title={`${formatX(edges[hover])} – ${formatX(edges[hover + 1])}`}
          rows={series.map((s) => ({ color: single ? undefined : s.color, label: s.label, value: formatY(s.values[hover]) }))}
        />
      )}
    </div>
  );
}
