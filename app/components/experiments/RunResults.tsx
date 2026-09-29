"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Gauge, HardDrive, Layers, Timer, Waypoints, Zap } from "lucide-react";

import { api, type Analytics, type Capture, type CaptureMetrics } from "@/lib/api";
import { formatBytes, formatMs, formatNumber } from "@/lib/format";
import { useInterval } from "@/lib/useInterval";
import { Alert, Loading, StatTile, buttonClass } from "@/components/ui";
import { AnalyticsCharts } from "./AnalyticsCharts";
import { CaptureDrawer } from "./CaptureDrawer";

type SortKey = "index" | keyof CaptureMetrics;

const COLUMNS: { key: SortKey; label: string; format: (c: Capture) => string }[] = [
  { key: "events", label: "Events", format: (c) => formatNumber(c.metrics.events ?? null, 0) },
  { key: "ttft_ms", label: "First event", format: (c) => formatMs(c.metrics.ttft_ms) },
  { key: "events_per_s", label: "Events/s", format: (c) => formatNumber(c.metrics.events_per_s ?? null) },
  { key: "stream_packets", label: "Packets", format: (c) => formatNumber(c.metrics.stream_packets ?? null, 0) },
  { key: "median_packet_bytes", label: "Median size", format: (c) => (c.metrics.median_packet_bytes != null ? `${c.metrics.median_packet_bytes} B` : "—") },
  { key: "median_gap_ms", label: "Median gap", format: (c) => formatMs(c.metrics.median_gap_ms) },
  { key: "stream_s", label: "Stream", format: (c) => (c.metrics.stream_s != null ? `${c.metrics.stream_s.toFixed(2)} s` : "—") },
  { key: "bytes", label: "Captured", format: (c) => formatBytes(c.metrics.bytes) },
];

const PAGE = 100;

export function RunResults({ runId, live }: { runId: string; live: boolean }) {
  const [data, setData] = useState<Analytics | null>(null);
  const [captures, setCaptures] = useState<Capture[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "index", desc: false });
  const [shown, setShown] = useState(PAGE);
  const [open, setOpen] = useState<number | null>(null);

  const refresh = useCallback(() => {
    Promise.all([
      api<Analytics>(`/data-collector/analytics?runs=${runId}`),
      api<Capture[]>(`/data-collector/runs/${runId}/captures`),
    ])
      .then(([a, c]) => {
        setData(a);
        setCaptures(c);
      })
      .catch((e: Error) => setError(e.message));
  }, [runId]);
  useEffect(refresh, [refresh]);
  useInterval(refresh, live ? 10000 : null);

  const sorted = useMemo(() => {
    if (!captures) return [];
    const value = (c: Capture) => (sort.key === "index" ? c.index : (c.metrics[sort.key] as number | null | undefined) ?? -Infinity);
    return [...captures].sort((a, b) => (value(a) - value(b)) * (sort.desc ? -1 : 1));
  }, [captures, sort]);

  if (error) return <Alert>{error}</Alert>;
  if (!data || !captures) return <Loading label="Analyzing captures…" />;

  const run = data.runs[0];
  const s = run.summary;
  if (s.captures === 0) {
    return <Alert tone="info">No captures yet. Results appear here as soon as the first prompt finishes.</Alert>;
  }

  function sortBy(key: SortKey) {
    setSort((cur) => ({ key, desc: cur.key === key ? !cur.desc : key !== "index" }));
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatTile label="Captures" value={s.captures.toLocaleString()} icon={Layers} />
        <StatTile label="First event" value={formatMs(s.median_ttft_ms)} hint="median" icon={Timer} />
        <StatTile label="Stream rate" value={s.median_events_per_s != null ? `${formatNumber(s.median_events_per_s)}/s` : "—"} hint="events, median" icon={Zap} />
        <StatTile label="Packet gap" value={formatMs(s.median_gap_ms)} hint="median" icon={Gauge} />
        <StatTile label="Packet size" value={s.median_packet_bytes != null ? `${s.median_packet_bytes} B` : "—"} hint="median payload" icon={Waypoints} />
        <StatTile label="Captured" value={formatBytes(s.total_bytes)} hint="all PCAPs" icon={HardDrive} />
      </div>

      <AnalyticsCharts data={data} series={[{ id: run.id, label: run.model, color: "var(--accent)" }]} />

      <div className="overflow-hidden rounded-2xl border border-hairline bg-surface shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
        <div className="flex items-center justify-between px-5 pt-5 pb-3">
          <div>
            <h2 className="text-sm font-semibold">Captures</h2>
            <p className="text-xs text-ink-3">Click a capture to see its packets on the wire, the prompt and the response.</p>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-y border-hairline bg-surface-2/60 text-xs text-ink-3">
              <tr>
                {[{ key: "index" as SortKey, label: "Prompt" }, ...COLUMNS].map((col) => (
                  <th key={col.key} className="px-3 py-2 font-medium whitespace-nowrap first:pl-5">
                    <button type="button" onClick={() => sortBy(col.key)} className="inline-flex items-center gap-1 hover:text-ink">
                      {col.label}
                      {sort.key === col.key && (sort.desc ? <ArrowDown className="h-3 w-3" /> : <ArrowUp className="h-3 w-3" />)}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--hairline)] tabular-nums">
              {sorted.slice(0, shown).map((c) => (
                <tr key={c.index} onClick={() => setOpen(c.index)} className="cursor-pointer hover:bg-surface-2/60">
                  <td className="py-2 pr-3 pl-5 whitespace-nowrap">
                    <span className="font-medium">#{String(c.prompt).padStart(2, "0")}</span>
                    {c.iteration != null && <span className="text-ink-3"> · {c.iteration}</span>}
                    <div className="text-xs text-ink-3">{c.category}</div>
                  </td>
                  {COLUMNS.map((col) => (
                    <td key={col.key} className="px-3 py-2 whitespace-nowrap text-ink-2">
                      {col.format(c)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {sorted.length > shown && (
          <div className="border-t border-hairline p-3 text-center">
            <button type="button" onClick={() => setShown((n) => n + PAGE)} className={buttonClass("ghost", "sm")}>
              Show {Math.min(PAGE, sorted.length - shown)} more of {sorted.length - shown}
            </button>
          </div>
        )}
      </div>

      {open !== null && <CaptureDrawer runId={runId} index={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
