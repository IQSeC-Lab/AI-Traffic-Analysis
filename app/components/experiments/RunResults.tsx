"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp } from "lucide-react";

import { api, type Analytics, type Capture, type CaptureMetrics, type Run } from "@/lib/api";
import { EXPERIMENTS } from "@/lib/experiments";
import { formatBytes, formatMs, formatNumber } from "@/lib/format";
import { useInterval } from "@/lib/useInterval";
import { Alert, Loading, StatTile, buttonClass } from "@/components/ui";
import type { Series } from "@/components/charts/scale";
import { CategoryChart, CompareChart, GapChart, SizeChart } from "./AnalyticsCharts";
import { CaptureDrawer } from "./CaptureDrawer";
import { comparesText, modelName, variantColor, variantLabel } from "./RunBadge";

type SortKey = "index" | "worker" | "variant" | keyof CaptureMetrics;

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

function median(values: (number | null | undefined)[]): number | null {
  const v = values.filter((x): x is number => x != null).sort((a, b) => a - b);
  if (v.length === 0) return null;
  const mid = Math.floor(v.length / 2);
  return v.length % 2 ? v[mid] : (v[mid - 1] + v[mid]) / 2;
}

type WorkerStats = { worker: number; gpus: number[] | null; count: number; ttft: number | null; rate: number | null };

/** Captures per worker, with each worker's medians, from the captures list. */
function workerStats(captures: Capture[]): WorkerStats[] {
  const groups = new Map<number, Capture[]>();
  for (const c of captures) {
    if (c.worker != null) groups.set(c.worker, [...(groups.get(c.worker) ?? []), c]);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a - b)
    .map(([worker, cs]) => ({
      worker,
      gpus: cs[0].gpus ?? null,
      count: cs.length,
      ttft: median(cs.map((c) => c.metrics.ttft_ms)),
      rate: median(cs.map((c) => c.metrics.events_per_s)),
    }));
}

const gpuText = (gpus: number[] | null) => (gpus == null ? "" : gpus.length ? `GPU ${gpus.join(", ")}` : "CPU");

export function RunResults({ run, live }: { run: Run; live: boolean }) {
  const [data, setData] = useState<Analytics | null>(null);
  const [captures, setCaptures] = useState<Capture[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "index", desc: false });
  const [shown, setShown] = useState(PAGE);
  const [open, setOpen] = useState<string | null>(null);
  const base = `/${run.experiment}/runs/${run.id}`;
  // What the run compares (temperature, model, network condition); the Data Collector compares nothing
  const info = EXPERIMENTS.find((e) => e.slug === run.experiment);
  const variable = info?.variable;
  const byPrompt = info?.ownPrompts ?? false; // Custom Prompts: each prompt is its own category
  const variantOrder = useMemo(() => new Map(run.variants.map((v, i) => [v.key, i])), [run.variants]);

  const refresh = useCallback(() => {
    Promise.all([api<Analytics>(`${base}/analytics`), api<Capture[]>(`${base}/captures`)])
      .then(([a, c]) => {
        setData(a);
        setCaptures(c);
      })
      .catch((e: Error) => setError(e.message));
  }, [base]);
  useEffect(refresh, [refresh]);
  useInterval(refresh, live ? 10000 : null);

  const sorted = useMemo(() => {
    if (!captures) return [];
    const value = (c: Capture) =>
      sort.key === "index"
        ? c.index * 100 + (variantOrder.get(c.variant) ?? 0)
        : sort.key === "worker"
          ? (c.worker ?? -Infinity)
          : sort.key === "variant"
            ? (variantOrder.get(c.variant) ?? -Infinity) * 1e7 + c.index
            : ((c.metrics[sort.key] as number | null | undefined) ?? -Infinity);
    return [...captures].sort((a, b) => (value(a) - value(b)) * (sort.desc ? -1 : 1));
  }, [captures, sort, variantOrder]);

  if (error) return <Alert>{error}</Alert>;
  if (!data || !captures) return <Loading label="Analyzing captures…" />;

  const s = data.summary!;
  // Runs with several workers get a tile comparing them, and a column saying which worker (and GPU) made each capture
  const workers = workerStats(captures);
  const byWorker = workers.length > 1;
  // One series per variant in the run's order and colors; the Data Collector's single one in the accent color
  const series: Series[] = variable
    ? run.variants.map((v, i) => ({ id: v.key, label: variantLabel(run.experiment, v), color: variantColor(i) }))
    : data.groups.map((g) => ({ id: g.key, label: g.label, color: "var(--accent)" }));
  const variantOf = new Map(run.variants.map((v, i) => [v.key, { label: variantLabel(run.experiment, v), color: variantColor(i) }]));
  const compares = comparesText(run);
  const heroFacts: [string, string][] = [
    ["Traffic captured", formatBytes(s.total_bytes)],
    ["Response", s.median_response_chars != null ? `${formatNumber(s.median_response_chars, 0)} chars` : "—"],
    ["Generation", s.median_duration_s != null ? `${formatNumber(s.median_duration_s)} s` : "—"],
    ["Stream packets", formatNumber(s.median_stream_packets, 0)],
    // One temperature for the whole run, unless it sweeps them. Runs from before it was recorded sampled at 0.7
    ...(run.experiment !== "temperature-change"
      ? [["Temperature", `${run.variants[0]?.temperature ?? 0.7}`] as [string, string]]
      : []),
    ...(byWorker
      ? [["Workers", `${workers.length} · ${gpuText([...new Set(workers.flatMap((w) => w.gpus ?? []))].sort((a, b) => a - b))}`] as [string, string]]
      : []),
  ];
  const headers: { key: SortKey; label: string }[] = [
    { key: "index", label: "Prompt" },
    ...(variable ? [{ key: "variant" as SortKey, label: variable.one[0].toUpperCase() + variable.one.slice(1) }] : []),
    ...(byWorker ? [{ key: "worker" as SortKey, label: "Worker" }] : []),
    ...COLUMNS,
  ];
  if (s.captures === 0) {
    return <Alert tone="info">No captures yet. Results appear here as soon as the first prompt finishes.</Alert>;
  }

  function sortBy(key: SortKey) {
    setSort((cur) => ({ key, desc: cur.key === key ? !cur.desc : key !== "index" && key !== "variant" }));
  }

  return (
    <div className="space-y-6">
      {/* Bento grid: the run at a glance on the left, its headline medians and charts around it */}
      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-4 row-span-2 flex flex-col rounded-2xl border border-hairline bg-surface p-6 shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
          <div className="text-xs font-medium text-ink-3">Captures</div>
          <div className="mt-2 text-6xl font-semibold tracking-tight tabular-nums">{s.captures.toLocaleString()}</div>
          <div className="mt-1 truncate text-sm text-ink-2" title={run.models.join(", ")}>
            {run.models.map(modelName).join(", ")}
          </div>
          {compares && <div className="truncate text-xs text-ink-3">{compares}</div>}
          <dl className="mt-auto divide-y divide-[var(--hairline)] pt-6 text-sm">
            {heroFacts.map(([k, v]) => (
              <div key={k} className="flex justify-between gap-3 py-2">
                <dt className="text-ink-3">{k}</dt>
                <dd className="truncate font-medium tabular-nums">{v}</dd>
              </div>
            ))}
          </dl>
          <div className="pt-1 text-[11px] text-ink-3">
            Medians over all captures{variable ? `, every ${variable.one} together` : ""}
          </div>
        </div>
        <StatTile className="col-span-2" label="First event" value={formatMs(s.median_ttft_ms)} hint="median" />
        <StatTile
          className="col-span-2"
          label="Stream rate"
          value={s.median_events_per_s != null ? `${formatNumber(s.median_events_per_s)}/s` : "—"}
          hint="events, median"
        />
        <StatTile className="col-span-2" label="Packet gap" value={formatMs(s.median_gap_ms)} hint="median" />
        <StatTile
          className="col-span-2"
          label="Packet size"
          value={s.median_packet_bytes != null ? `${s.median_packet_bytes} B` : "—"}
          hint="median payload"
        />
        {variable ? (
          <>
            <CompareChart data={data} series={series} variable={variable.one} height={200} className="col-span-8" />
            <GapChart data={data} series={series} height={240} className="col-span-7" />
            <SizeChart data={data} series={series} height={240} className="col-span-5" />
            <CategoryChart data={data} series={series} byPrompt={byPrompt} height={240} className="col-span-12" />
          </>
        ) : (
          <>
            <GapChart data={data} series={series} height={230} className="col-span-8" />
            <CategoryChart data={data} series={series} byPrompt={byPrompt} height={240} className="col-span-7" />
            <SizeChart data={data} series={series} height={240} className="col-span-5" />
          </>
        )}
        {byWorker && <WorkersTile workers={workers} total={captures.length} className="col-span-12" />}
      </div>

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
                {headers.map((col) => (
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
                <tr key={c.key} onClick={() => setOpen(c.key)} className="cursor-pointer hover:bg-surface-2/60">
                  <td className="py-2 pr-3 pl-5 whitespace-nowrap">
                    <span className="font-medium">#{String(c.prompt).padStart(2, "0")}</span>
                    {c.iteration != null && <span className="text-ink-3"> · {c.iteration}</span>}
                    {!byPrompt && <div className="text-xs text-ink-3">{c.category}</div>}
                  </td>
                  {variable && (
                    <td className="px-3 py-2 whitespace-nowrap">
                      <span className="flex max-w-56 items-center gap-2">
                        <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: variantOf.get(c.variant)?.color }} />
                        <span className="truncate">{variantOf.get(c.variant)?.label ?? c.variant}</span>
                      </span>
                    </td>
                  )}
                  {byWorker && (
                    <td className="px-3 py-2 whitespace-nowrap">
                      {c.worker != null ? (
                        <>
                          <span className="font-medium">w{c.worker}</span>
                          <div className="text-xs text-ink-3">
                            {c.gpus == null ? "" : c.gpus.length ? `GPU ${c.gpus.join(", ")}` : "CPU"}
                          </div>
                        </>
                      ) : (
                        "—"
                      )}
                    </td>
                  )}
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

      {open !== null && <CaptureDrawer run={run} captureKey={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function WorkersTile({ workers, total, className }: { workers: WorkerStats[]; total: number; className: string }) {
  return (
    <section className={`rounded-2xl border border-hairline bg-surface p-5 shadow-[0_1px_2px_rgba(0,0,0,0.04)] ${className}`}>
      <h2 className="text-sm font-semibold">Workers</h2>
      <p className="mt-0.5 text-xs text-ink-3">
        The prompts were divided between the workers. Each ran its own copy of the model, with its own network and capture.
      </p>
      <div
        className="mt-4 grid gap-3"
        style={{ gridTemplateColumns: `repeat(${Math.min(workers.length, 4)}, minmax(0, 1fr))` }}
      >
        {workers.map((w) => {
          const color = `var(--series-${((w.worker - 1) % 8) + 1})`;
          const pct = total ? (w.count / total) * 100 : 0;
          return (
            <div key={w.worker} className="rounded-xl border border-hairline p-4">
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="flex items-center gap-1.5 font-medium">
                  <span className="h-2 w-2 rounded-full" style={{ background: color }} />
                  Worker {w.worker}
                </span>
                <span className="text-ink-3">{gpuText(w.gpus)}</span>
              </div>
              <div className="mt-2 flex items-baseline gap-1.5">
                <span className="text-2xl font-semibold tracking-tight tabular-nums">{w.count}</span>
                <span className="text-xs text-ink-3">captures · {Math.round(pct)}%</span>
              </div>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-2">
                <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
              </div>
              <dl className="mt-3 grid grid-cols-2 gap-2 text-xs">
                <div>
                  <dt className="text-ink-3">First event</dt>
                  <dd className="font-medium tabular-nums">{formatMs(w.ttft)}</dd>
                </div>
                <div>
                  <dt className="text-ink-3">Events/s</dt>
                  <dd className="font-medium tabular-nums">{formatNumber(w.rate)}</dd>
                </div>
              </dl>
            </div>
          );
        })}
      </div>
    </section>
  );
}
