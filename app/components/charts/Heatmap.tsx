"use client";

import { useState } from "react";

import { Tooltip } from "./ChartCard";
import { useWidth } from "./scale";

const LABEL_W = 132;
const HEADER_H = 26;
const ROW_H = 30;
const GAP = 2; // surface gap between cells

/**
 * A grid of standardized values on a diverging scale: below the column's mean in blue,
 * above it in red, the mean itself the neutral midpoint. `limit` is the value the scale
 * ends at, shared by heatmaps shown side by side so their colors mean the same.
 */
export function Heatmap({
  rows,
  columns,
  values,
  limit,
  detail,
  ariaLabel,
}: {
  rows: string[];
  columns: string[];
  values: (number | null)[][];
  limit: number;
  /** The tooltip's second line for a cell, e.g. its unscaled value. */
  detail?: (row: number, column: number) => string;
  ariaLabel: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<[number, number] | null>(null);
  const cellW = Math.max(0, (width - LABEL_W) / Math.max(1, columns.length));
  const height = HEADER_H + rows.length * ROW_H;

  return (
    <div ref={ref} className="relative" style={{ height }}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={ariaLabel} className="block" onPointerLeave={() => setHover(null)}>
          {columns.map((c, j) => (
            <text key={c} x={LABEL_W + j * cellW + cellW / 2} y={HEADER_H - 10} textAnchor="middle" className="fill-ink-3 text-[11px]">
              {c}
            </text>
          ))}
          {rows.map((r, i) => (
            <g key={r}>
              <text x={LABEL_W - 10} y={HEADER_H + i * ROW_H + ROW_H / 2} dy="0.32em" textAnchor="end" className="fill-ink-2 text-xs">
                {r}
              </text>
              {columns.map((c, j) => {
                const v = values[i]?.[j];
                // Up to 72% of the pole's color, so the value stays readable in the ink color on every cell
                const strength = v == null ? 0 : Math.min(1, Math.abs(v) / (limit || 1)) * 72;
                const on = hover?.[0] === i && hover?.[1] === j;
                return (
                  <g key={c} onPointerEnter={() => setHover([i, j])}>
                    <rect
                      x={LABEL_W + j * cellW + GAP / 2}
                      y={HEADER_H + i * ROW_H + GAP / 2}
                      width={Math.max(0, cellW - GAP)}
                      height={ROW_H - GAP}
                      rx={4}
                      fill={
                        v == null
                          ? "var(--surface-2)"
                          : `color-mix(in oklab, var(${v < 0 ? "--series-1" : "--series-8"}) ${strength.toFixed(1)}%, var(--diverge-mid))`
                      }
                      stroke={on ? "var(--ink)" : "none"}
                      strokeWidth={1.5}
                    />
                    <text
                      x={LABEL_W + j * cellW + cellW / 2}
                      y={HEADER_H + i * ROW_H + ROW_H / 2}
                      dy="0.32em"
                      textAnchor="middle"
                      className="pointer-events-none fill-ink text-[11px] tabular-nums"
                    >
                      {v == null ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(1)}`}
                    </text>
                  </g>
                );
              })}
            </g>
          ))}
        </svg>
      )}
      {hover && values[hover[0]]?.[hover[1]] != null && (
        <Tooltip
          x={LABEL_W + hover[1] * cellW + cellW / 2}
          y={HEADER_H + hover[0] * ROW_H}
          width={width}
          title={`${rows[hover[0]]} · ${columns[hover[1]]}`}
          rows={[
            { label: "standard deviations from the mean", value: `${values[hover[0]][hover[1]]! > 0 ? "+" : ""}${values[hover[0]][hover[1]]!.toFixed(2)}` },
            ...(detail ? [{ label: "median", value: detail(hover[0], hover[1]) }] : []),
          ]}
        />
      )}
    </div>
  );
}

/** The scale's key: two steps below the mean, the midpoint, two above. */
export function DivergingLegend({ limit }: { limit: number }) {
  const steps = [-1, -0.5, 0, 0.5, 1];
  return (
    <div className="flex items-center gap-2 text-[11px] text-ink-3 tabular-nums">
      <span>−{limit.toFixed(1)} below the mean</span>
      <span className="flex gap-0.5">
        {steps.map((step) => (
          <span
            key={step}
            className="h-2.5 w-6 rounded-[3px]"
            style={{
              background: `color-mix(in oklab, var(${step < 0 ? "--series-1" : "--series-8"}) ${Math.abs(step) * 72}%, var(--diverge-mid))`,
            }}
          />
        ))}
      </span>
      <span>above +{limit.toFixed(1)}</span>
    </div>
  );
}
