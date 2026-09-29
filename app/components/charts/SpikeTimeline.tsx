"use client";

import { useMemo, useState } from "react";

import { Tooltip } from "./ChartCard";
import { MARGIN, linear, niceTicks, useWidth } from "./scale";

/**
 * Events over time, one thin stem per event (e.g. each packet of the stream,
 * height = its size). The pointer snaps to the nearest event.
 */
export function SpikeTimeline({
  points,
  color,
  formatX,
  formatY,
  itemLabel,
  height = 220,
  ariaLabel,
}: {
  points: [number, number][];
  color: string;
  formatX: (v: number) => string;
  formatY: (v: number) => string;
  itemLabel: string;
  height?: number;
  ariaLabel: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  const layout = useMemo(() => {
    if (!width || points.length === 0) return null;
    const plotRight = width - MARGIN.right;
    const plotBottom = height - MARGIN.bottom;
    const maxX = points[points.length - 1][0] || 1;
    const xTicks = niceTicks(0, maxX, 6).filter((t) => t <= maxX * 1.0001);
    const yTicks = niceTicks(0, Math.max(...points.map((p) => p[1])) || 1, 4);
    const x = linear([0, maxX], [MARGIN.left, plotRight]);
    const y = linear([0, yTicks[yTicks.length - 1]], [plotBottom, MARGIN.top]);
    const stems = points.map(([px, py]) => `M${x(px).toFixed(1)},${plotBottom}V${y(py).toFixed(1)}`).join("");
    return { plotRight, plotBottom, x, y, xTicks, yTicks, stems };
  }, [width, height, points]);

  function onMove(e: React.PointerEvent<SVGSVGElement>) {
    if (!layout) return;
    const px = e.clientX - e.currentTarget.getBoundingClientRect().left;
    // Points are sorted by x: binary search for the nearest.
    let lo = 0;
    let hi = points.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (layout.x(points[mid][0]) < px) lo = mid + 1;
      else hi = mid;
    }
    const prev = Math.max(0, lo - 1);
    const best = Math.abs(layout.x(points[prev][0]) - px) < Math.abs(layout.x(points[lo][0]) - px) ? prev : lo;
    setHover(best);
  }

  return (
    <div ref={ref} className="relative" style={{ height }}>
      {layout && (
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={ariaLabel}
          className="block touch-none"
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
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
          <path d={layout.stems} stroke={color} strokeWidth={1.5} opacity={0.85} />
          <line x1={MARGIN.left} x2={layout.plotRight} y1={layout.plotBottom} y2={layout.plotBottom} stroke="var(--axis)" />
          {hover !== null && (
            <g>
              <line
                x1={layout.x(points[hover][0])}
                x2={layout.x(points[hover][0])}
                y1={MARGIN.top}
                y2={layout.plotBottom}
                stroke="var(--axis)"
              />
              <circle
                cx={layout.x(points[hover][0])}
                cy={layout.y(points[hover][1])}
                r={4}
                fill={color}
                stroke="var(--surface)"
                strokeWidth={2}
              />
            </g>
          )}
        </svg>
      )}
      {layout && hover !== null && (
        <Tooltip
          x={layout.x(points[hover][0])}
          y={MARGIN.top}
          width={width}
          title={`${itemLabel} ${hover + 1} · ${formatX(points[hover][0])}`}
          rows={[{ label: "", value: formatY(points[hover][1]) }]}
        />
      )}
    </div>
  );
}
