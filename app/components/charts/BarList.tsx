"use client";

import type { Series } from "./scale";

type BarRow = Series & { value: number | null; note?: string };

/**
 * Horizontal bars from a shared zero, one per row, each labeled with its value.
 * Rows share the height evenly (up to 44px each) and sit centered in it.
 */
export function BarList({
  rows,
  format,
  height = 200,
  ariaLabel,
}: {
  rows: BarRow[];
  format: (v: number) => string;
  height?: number;
  ariaLabel: string;
}) {
  const max = Math.max(0, ...rows.map((r) => r.value ?? 0));
  const pitch = Math.min(44, height / Math.max(1, rows.length));
  const bar = Math.max(10, Math.round(pitch * 0.55));
  return (
    <div role="img" aria-label={ariaLabel} className="flex flex-col justify-center" style={{ height }}>
      {/* One grid for every row, so the labels take the width of the longest and the bars line up */}
      <div
        className="grid grid-cols-[minmax(0,max-content)_minmax(0,1fr)_max-content] items-center gap-x-3 text-xs"
        style={{ gridAutoRows: pitch }}
      >
        {rows.map((r) => (
          <div key={r.id} className="contents" title={r.note ? `${r.label} · ${r.note}` : r.label}>
            <span className="flex max-w-96 min-w-0 items-center gap-2 text-ink-2">
              <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: r.color }} />
              <span className="truncate">{r.label}</span>
            </span>
            <div className="relative border-l border-axis" style={{ height: bar }}>
              {r.value != null && max > 0 && (
                <div
                  className="absolute inset-y-0 left-0 rounded-r-[4px]"
                  style={{ width: `${(r.value / max) * 100}%`, background: r.color }}
                />
              )}
            </div>
            <span className="text-right font-semibold text-ink tabular-nums">{r.value == null ? "—" : format(r.value)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
