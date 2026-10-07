"use client";

import { useState } from "react";

import { Tooltip } from "./ChartCard";
import { linear, niceTicks, useWidth } from "./scale";

const LEFT = 72;
const RIGHT = 14;
const TOP = 8;
const ROW_H = 22;
const AXIS_H = 26;

/** One lane per agent: a bar for each of its calls, from when it started to when it ended. */
export function CallLanes({
  lanes,
  calls,
  formatX,
  ariaLabel,
}: {
  lanes: string[];
  calls: [string, number, number][]; // lane, start, end
  formatX: (v: number) => string;
  ariaLabel: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const height = TOP + lanes.length * ROW_H + AXIS_H;
  const end = Math.max(1e-9, ...calls.map((c) => c[2]));
  const ticks = niceTicks(0, end, 5).filter((t) => t <= end * 1.001);
  const x = linear([0, end], [LEFT, Math.max(LEFT, width - RIGHT)]);
  const bottom = TOP + lanes.length * ROW_H;

  return (
    <div ref={ref} className="relative" style={{ height }}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={ariaLabel} className="block" onPointerLeave={() => setHover(null)}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={x(t)} x2={x(t)} y1={TOP} y2={bottom} stroke="var(--hairline)" />
              <text x={x(t)} y={bottom + 16} textAnchor="middle" className="fill-ink-3 text-[11px] tabular-nums">
                {formatX(t)}
              </text>
            </g>
          ))}
          {lanes.map((lane, i) => (
            <text key={lane} x={LEFT - 10} y={TOP + i * ROW_H + ROW_H / 2} dy="0.32em" textAnchor="end" className="fill-ink-2 text-[11px]">
              {lane}
            </text>
          ))}
          {calls.map(([lane, start, stop], n) => {
            const i = lanes.indexOf(lane);
            if (i < 0) return null;
            return (
              <rect
                key={n}
                x={x(start)}
                y={TOP + i * ROW_H + 5}
                width={Math.max(2, x(stop) - x(start) - 1)}
                height={ROW_H - 10}
                rx={2}
                fill="var(--accent)"
                stroke={hover === n ? "var(--ink)" : "none"}
                strokeWidth={1.5}
                onPointerEnter={() => setHover(n)}
              />
            );
          })}
          <line x1={LEFT} x2={width - RIGHT} y1={bottom} y2={bottom} stroke="var(--axis)" />
        </svg>
      )}
      {hover !== null && calls[hover] && (
        <Tooltip
          x={x((calls[hover][1] + calls[hover][2]) / 2)}
          y={TOP + Math.max(0, lanes.indexOf(calls[hover][0])) * ROW_H}
          width={width}
          title={calls[hover][0]}
          rows={[
            { label: "call", value: formatX(calls[hover][2] - calls[hover][1]) },
            { label: "started at", value: formatX(calls[hover][1]) },
          ]}
        />
      )}
    </div>
  );
}
