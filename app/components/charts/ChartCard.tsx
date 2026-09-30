"use client";

import { useState, type ReactNode } from "react";

import { Segmented } from "@/components/ui";
import type { Series } from "./scale";

export type TableData = { columns: string[]; rows: ReactNode[][] };

/** A chart with its title, legend and a table view (the accessible twin of every chart). */
export function ChartCard({
  title,
  subtitle,
  legend,
  legendShape = "line",
  controls,
  table,
  children,
  footer,
  height,
  className = "",
}: {
  title: string;
  subtitle?: ReactNode;
  legend?: Series[];
  legendShape?: "line" | "rect";
  controls?: ReactNode;
  table: TableData;
  children: ReactNode;
  footer?: ReactNode;
  /** The chart's height. Given, the table view scrolls inside the same height, so toggling never reflows a grid. */
  height?: number;
  className?: string;
}) {
  const [view, setView] = useState<"chart" | "table">("chart");
  return (
    <figure className={`flex flex-col rounded-2xl border border-hairline bg-surface p-5 shadow-[0_1px_2px_rgba(0,0,0,0.04)] ${className}`}>
      <div className="mb-4 flex items-start justify-between gap-3">
        <figcaption className="min-w-0 flex-1">
          <div className="text-sm font-semibold">{title}</div>
          {subtitle && <div className="mt-0.5 text-xs text-ink-3">{subtitle}</div>}
        </figcaption>
        <div className="flex shrink-0 items-center gap-2">
          {controls}
          <Segmented
            value={view}
            onChange={setView}
            options={[
              { value: "chart", label: "Chart" },
              { value: "table", label: "Table" },
            ]}
          />
        </div>
      </div>

      {legend && legend.length > 1 && view === "chart" && (
        <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1.5">
          {legend.map((s) => (
            <span key={s.id} className="inline-flex items-center gap-1.5 text-xs text-ink-2">
              {legendShape === "line" ? (
                <span className="h-0.5 w-3.5 rounded-full" style={{ background: s.color }} />
              ) : (
                <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: s.color }} />
              )}
              {s.label}
            </span>
          ))}
        </div>
      )}

      {view === "chart" ? (
        <div className="mt-auto">{children}</div>
      ) : (
        <div
          className={`mt-auto overflow-auto rounded-lg border border-hairline ${height ? "" : "max-h-80"}`}
          style={height ? { height } : undefined}
        >
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-surface-2 text-ink-3">
              <tr>
                {table.columns.map((c) => (
                  <th key={c} className="px-3 py-2 font-medium whitespace-nowrap">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--hairline)] tabular-nums">
              {table.rows.map((row, i) => (
                <tr key={i}>
                  {row.map((cell, j) => (
                    <td key={j} className="px-3 py-1.5 whitespace-nowrap text-ink-2">
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {footer && <div className="mt-3 text-xs text-ink-3">{footer}</div>}
    </figure>
  );
}

/** Tooltip rows: value first (strong), series name second, keyed by a short line of the series color. */
export function Tooltip({
  x,
  y,
  width,
  title,
  rows,
}: {
  x: number;
  y: number;
  width: number;
  title: string;
  rows: { color?: string; label: string; value: string }[];
}) {
  const flip = x > width * 0.6;
  return (
    <div
      className="pointer-events-none absolute z-10 min-w-36 rounded-lg border border-hairline bg-surface px-3 py-2 text-xs shadow-lg"
      style={{ left: x, top: Math.max(0, y - 12), transform: `translate(${flip ? "calc(-100% - 14px)" : "14px"}, 0)` }}
    >
      <div className="mb-1 font-medium text-ink-3">{title}</div>
      {rows.map((r) => (
        <div key={r.label} className="flex items-center gap-2 py-0.5">
          {r.color && <span className="h-0.5 w-3 shrink-0 rounded-full" style={{ background: r.color }} />}
          <span className="font-semibold text-ink tabular-nums">{r.value}</span>
          <span className="truncate text-ink-3">{r.label}</span>
        </div>
      ))}
    </div>
  );
}
