"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, X } from "lucide-react";

import {
  api,
  type AgenticAnalytics,
  type AgenticCapture,
  type AgenticCaptureDetail,
  type AgenticMetrics,
  type Run,
  type TrafficHeatmap,
} from "@/lib/api";
import { formatBytes, formatMs, formatNumber, formatPercent, workerLabel } from "@/lib/format";
import { useInterval } from "@/lib/useInterval";
import { Alert, Loading, StatTile, buttonClass } from "@/components/ui";
import { CallLanes } from "@/components/charts/CallLanes";
import { ChartCard } from "@/components/charts/ChartCard";
import { DivergingLegend, Heatmap } from "@/components/charts/Heatmap";
import { SpikeTimeline } from "@/components/charts/SpikeTimeline";
import type { Series } from "@/components/charts/scale";
import { CategoryChart, CompareChart, GapChart, SizeChart, type Metric } from "./AnalyticsCharts";
import { modelName, variantColor } from "./RunBadge";

// The measurements of an agentic run: over a task's encrypted application packets, on every connection
const count = (v: number) => formatNumber(v, 0);
const secondsText = (v: number) => `${formatNumber(v)} s`;
const VALUE_FORMAT: Record<string, (v: number) => string> = {
  total_packets: count,
  total_bytes: (v) => formatBytes(v),
  task_duration: secondsText,
  packets_per_second: (v) => `${formatNumber(v)}/s`,
  total_bursts: count,
  idle_time_fraction: (v) => formatPercent(v, 0),
};
const METRICS: Metric[] = [
  { key: "median_total_packets", label: "Packets", format: count },
  { key: "median_total_bytes", label: "Bytes", format: VALUE_FORMAT.total_bytes },
  { key: "median_task_duration", label: "Duration", format: secondsText },
  { key: "median_packets_per_second", label: "Packet rate", format: VALUE_FORMAT.packets_per_second },
  { key: "median_total_bursts", label: "Bursts", format: count },
  { key: "median_idle_time_fraction", label: "Idle time", format: VALUE_FORMAT.idle_time_fraction },
  { key: "median_calls", label: "LLM calls", format: count },
  { key: "median_agents", label: "Agents", format: count },
  { key: "median_gap_ms", label: "Packet gap", format: formatMs },
];

type SortKey = "index" | "variant" | keyof AgenticMetrics;
const value = (v: number | null | undefined, format: (v: number) => string) => (v == null ? "—" : format(v));
const COLUMNS: { key: keyof AgenticMetrics; label: string; format: (v: number) => string }[] = [
  { key: "calls", label: "LLM calls", format: count },
  { key: "agents", label: "Agents", format: count },
  { key: "total_packets", label: "Packets", format: count },
  { key: "total_bytes", label: "Bytes", format: VALUE_FORMAT.total_bytes },
  { key: "task_duration", label: "Duration", format: secondsText },
  { key: "packets_per_second", label: "Packet rate", format: VALUE_FORMAT.packets_per_second },
  { key: "total_bursts", label: "Bursts", format: count },
  { key: "idle_time_fraction", label: "Idle time", format: VALUE_FORMAT.idle_time_fraction },
];
const STATUS_TEXT = { running: "Running", completed: "Completed", failed: "Not completed" };
const PAGE = 100;

const taskName = (c: Pick<AgenticCapture, "category" | "task_id" | "prompt">) => `${c.category ?? "Task"} ${c.task_id ?? c.prompt}`;

export function AgenticResults({ run, live }: { run: Run; live: boolean }) {
  const [data, setData] = useState<AgenticAnalytics | null>(null);
  const [captures, setCaptures] = useState<AgenticCapture[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "index", desc: false });
  const [shown, setShown] = useState(PAGE);
  const [open, setOpen] = useState<string | null>(null);
  const base = `/${run.experiment}/runs/${run.id}`;
  const variantOrder = useMemo(() => new Map(run.variants.map((v, i) => [v.key, i])), [run.variants]);

  const refresh = useCallback(() => {
    Promise.all([api<AgenticAnalytics>(`${base}/analytics`), api<AgenticCapture[]>(`${base}/captures`)])
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
    const of = (c: AgenticCapture) =>
      sort.key === "index"
        ? c.index * 100 + (variantOrder.get(c.variant) ?? 0)
        : sort.key === "variant"
          ? (variantOrder.get(c.variant) ?? -Infinity) * 1e7 + c.index
          : (c.metrics[sort.key] ?? -Infinity);
    return [...captures].sort((a, b) => (of(a) - of(b)) * (sort.desc ? -1 : 1));
  }, [captures, sort, variantOrder]);

  if (error) return <Alert>{error}</Alert>;
  if (!data || !captures) return <Loading label="Analyzing captures…" />;
  if (captures.length === 0) {
    return <Alert tone="info">No captures yet. Results appear here as soon as the first task finishes.</Alert>;
  }

  const s = data.summary;
  const series: Series[] = run.variants.map((v, i) => ({ id: v.key, label: v.label, color: variantColor(i) }));
  const variantOf = new Map(series.map((x) => [x.id, x]));
  const heroFacts: [string, string][] = [
    ["Traffic captured", formatBytes(s.total_bytes)],
    ["LLM calls", value(s.median_calls, count)],
    ["Agents", value(s.median_agents, count)],
    ["Duration", value(s.median_task_duration, secondsText)],
    ...(s.failed ? [["Not completed", `${s.failed}`] as [string, string]] : []),
  ];
  const headers: { key: SortKey; label: string }[] = [
    { key: "index", label: "Task" },
    { key: "variant", label: "Topology" },
    ...COLUMNS,
  ];

  function sortBy(key: SortKey) {
    setSort((cur) => ({ key, desc: cur.key === key ? !cur.desc : key !== "index" && key !== "variant" }));
  }

  return (
    <div className="space-y-6">
      {/* Bento grid: the run at a glance on the left, its headline medians and charts around it */}
      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-4 row-span-2 flex flex-col rounded-2xl border border-hairline bg-surface p-6 shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
          <div className="text-xs font-medium text-ink-3">Tasks completed</div>
          <div className="mt-2 text-6xl font-semibold tracking-tight tabular-nums">{s.captures.toLocaleString()}</div>
          <div className="mt-1 truncate text-sm text-ink-2" title={run.models.join(", ")}>
            {run.models.map(modelName).join(", ")}
          </div>
          <div className="truncate text-xs text-ink-3">{run.variants.map((v) => v.label).join(" and ")}</div>
          <dl className="mt-auto divide-y divide-[var(--hairline)] pt-6 text-sm">
            {heroFacts.map(([k, v]) => (
              <div key={k} className="flex justify-between gap-3 py-2">
                <dt className="text-ink-3">{k}</dt>
                <dd className="truncate font-medium tabular-nums">{v}</dd>
              </div>
            ))}
          </dl>
          <div className="pt-1 text-[11px] text-ink-3">Medians per task, over the completed ones of every topology</div>
        </div>
        <StatTile className="col-span-2" label="Packets" value={value(s.median_total_packets, count)} hint="encrypted, median" />
        <StatTile className="col-span-2" label="Bursts" value={value(s.median_total_bursts, count)} hint="direction changes, median" />
        <StatTile className="col-span-2" label="Idle time" value={value(s.median_idle_time_fraction, VALUE_FORMAT.idle_time_fraction)} hint="gaps over 1 s, median" />
        <StatTile className="col-span-2" label="Packet rate" value={value(s.median_packets_per_second, VALUE_FORMAT.packets_per_second)} hint="median" />
        <CompareChart data={data} series={series} variable="topology" metrics={METRICS} height={200} className="col-span-8" />
        <HeatmapTile heatmap={data.heatmap} className="col-span-12" />
        <CategoryChart data={data} series={series} metrics={METRICS} unit="task category" height={240} className="col-span-12" />
        <GapChart
          data={data}
          series={series}
          height={240}
          className="col-span-7"
          title="Time between packets from the model server"
          subtitle="Encrypted packets to the agents, over every connection of a task · share of gaps, log scale"
        />
        <SizeChart
          data={data}
          series={series}
          height={240}
          className="col-span-5"
          title="Packet sizes"
          subtitle="Encrypted payload of each packet to the agents · share of packets"
        />
      </div>

      <div className="overflow-hidden rounded-2xl border border-hairline bg-surface shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
        <div className="px-5 pt-5 pb-3">
          <h2 className="text-sm font-semibold">Captures</h2>
          <p className="text-xs text-ink-3">One per task, repetition and topology. Click one to see each agent&apos;s calls and its packets on the wire.</p>
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
                    <span className="font-medium">{taskName(c)}</span>
                    {c.iteration != null && <span className="text-ink-3"> · {c.iteration}</span>}
                    {c.status && c.status !== "completed" && (
                      <div className={`text-xs ${c.status === "failed" ? "text-critical-text" : "text-ink-3"}`}>{STATUS_TEXT[c.status]}</div>
                    )}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    <span className="flex items-center gap-2">
                      <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: variantOf.get(c.variant)?.color }} />
                      {variantOf.get(c.variant)?.label ?? c.variant}
                    </span>
                  </td>
                  {COLUMNS.map((col) => (
                    <td key={col.key} className="px-3 py-2 whitespace-nowrap text-ink-2">
                      {value(c.metrics[col.key], col.format)}
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

      {open !== null && <AgenticCaptureDrawer run={run} captureKey={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

/** The dataset's traffic heatmap: task categories against traffic measurements, one grid per topology. */
function HeatmapTile({ heatmap, className }: { heatmap: TrafficHeatmap; className: string }) {
  const shown = heatmap.topologies.filter((t) => t.categories.length > 0);
  const columns = heatmap.metrics.map((m) => m.label);
  // One scale for every grid, so a color means the same under each topology
  const limit = Math.max(1, ...shown.flatMap((t) => t.z.flat().map((v) => Math.abs(v ?? 0))));
  const raw = (key: string, v: number | null) => value(v, VALUE_FORMAT[key] ?? formatNumber);
  return (
    <ChartCard
      title="Traffic by task category"
      subtitle="Each measurement's median per category, in standard deviations from the mean of the categories. A task counts once, whatever its repetitions; counts, bytes, durations and rates are compared on a log scale."
      className={className}
      footer={shown.length > 0 ? <DivergingLegend limit={limit} /> : undefined}
      table={{
        columns: ["Topology", "Category", "Tasks", ...columns],
        rows: shown.flatMap((t) =>
          t.categories.map((c, i) => [t.label, c, t.tasks[i], ...heatmap.metrics.map((m, j) => raw(m.key, t.medians[i][j]))]),
        ),
      }}
    >
      {shown.length === 0 ? (
        <div className="flex h-40 items-center justify-center text-sm text-ink-3">No completed task yet.</div>
      ) : (
        <div className={`grid gap-8 ${shown.length > 1 ? "grid-cols-2" : ""}`}>
          {shown.map((t) => (
            <div key={t.key} className="min-w-0">
              <div className="mb-1 text-xs font-medium text-ink-2">
                {t.label}
                {t.categories.length < 2 && <span className="font-normal text-ink-3"> · one category, so nothing to compare it with</span>}
              </div>
              <Heatmap
                rows={t.categories}
                columns={columns}
                values={t.z}
                limit={limit}
                detail={(i, j) => raw(heatmap.metrics[j].key, t.medians[i][j])}
                ariaLabel={`Traffic by task category, ${t.label} topology`}
              />
            </div>
          ))}
        </div>
      )}
    </ChartCard>
  );
}

const seconds = (v: number) => `${+v.toFixed(v < 10 ? 2 : 1)} s`;

/** One task's capture: which agent called the model when, and the packets on the wire. */
function AgenticCaptureDrawer({ run, captureKey, onClose }: { run: Run; captureKey: string; onClose: () => void }) {
  const [detail, setDetail] = useState<AgenticCaptureDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const url = `/${run.experiment}/runs/${run.id}/captures/${encodeURIComponent(captureKey)}`;

  useEffect(() => {
    api<AgenticCaptureDetail>(url)
      .then(setDetail)
      .catch((e: Error) => setError(e.message));
  }, [url]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const m = detail?.metrics;
  const variant = run.variants.find((v) => v.key === detail?.variant);
  const incoming = detail?.timeline.filter((p) => p[2] < 0).map((p): [number, number] => [p[0], p[1]]) ?? [];
  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="absolute inset-y-0 right-0 flex w-full max-w-3xl flex-col border-l border-hairline bg-page shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-hairline bg-surface px-6 py-4">
          <div>
            <div className="text-xs font-medium text-ink-3">
              {variant ? `${variant.label} topology` : "Capture"}
              {detail?.worker != null && ` · ${workerLabel(detail.worker, detail.gpus)}`}
            </div>
            <h2 className="text-lg font-semibold tracking-tight">
              {detail ? taskName(detail) : "Task"}
              {detail?.iteration != null && <span className="font-normal text-ink-3"> · repetition {detail.iteration}</span>}
            </h2>
          </div>
          <div className="flex items-center gap-2">
            <a href={`/api${url}/pcap`} className={buttonClass("secondary", "sm")} download>
              Download PCAP
            </a>
            <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-ink-3 hover:bg-surface-2 hover:text-ink" aria-label="Close">
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto p-6">
          {error && <Alert>{error}</Alert>}
          {!detail && !error && <Loading />}
          {detail && m && (
            <>
              {detail.status === "failed" && <Alert tone="warning">The agents did not complete this task. {detail.error}</Alert>}
              {detail.status === "running" && <Alert tone="info">The agents are still working on this task.</Alert>}
              <dl className="grid grid-cols-4 gap-px overflow-hidden rounded-2xl border border-hairline bg-[var(--hairline)]">
                {COLUMNS.map((col) => (
                  <div key={col.key} className="bg-surface px-4 py-3">
                    <dt className="text-[11px] text-ink-3">{col.label}</dt>
                    <dd className="mt-0.5 text-base font-semibold">{value(m[col.key], col.format)}</dd>
                  </div>
                ))}
              </dl>

              <ChartCard
                title="LLM calls by agent"
                subtitle="Each bar is one call to the model server, from when the agent sent it to when the answer was complete"
                table={{
                  columns: ["Agent", "Calls", "Packets", "Bytes"],
                  rows: detail.agents.map((a) => [a.agent, a.calls, a.packets.toLocaleString(), formatBytes(a.bytes)]),
                }}
                footer={
                  detail.unattributed_packets > 0
                    ? `${detail.unattributed_packets.toLocaleString()} packets belong to no agent's call: MARBLE's own calls are not attributed to an agent.`
                    : undefined
                }
              >
                {detail.calls.length > 0 ? (
                  <CallLanes lanes={detail.agents.map((a) => a.agent)} calls={detail.calls} formatX={seconds} ariaLabel="LLM calls of each agent over time" />
                ) : (
                  <p className="py-10 text-center text-sm text-ink-3">No call was recorded for this task.</p>
                )}
              </ChartCard>

              <ChartCard
                title="Packets from the model server"
                subtitle="Each stem is one encrypted packet to the agents: when it was sent and its payload size"
                table={{
                  columns: ["Packet", "Time", "Payload"],
                  rows: incoming.map(([t, size], i) => [i + 1, seconds(t), `${size} B`]),
                }}
                footer={detail.downsampled ? "Long capture: every other point is shown." : undefined}
              >
                {incoming.length > 0 ? (
                  <SpikeTimeline
                    points={incoming}
                    color="var(--accent)"
                    formatX={seconds}
                    formatY={(v) => formatBytes(v)}
                    itemLabel="Packet"
                    ariaLabel="Packets from the model server over time"
                  />
                ) : (
                  <p className="py-10 text-center text-sm text-ink-3">No packets from the model server in this capture.</p>
                )}
              </ChartCard>

              <div className="rounded-2xl border border-hairline bg-surface p-4">
                <div className="mb-2 text-xs font-medium text-ink-3">Task</div>
                <p className="max-h-72 overflow-y-auto text-sm leading-relaxed whitespace-pre-wrap text-ink-2">{detail.task_text || "Not recorded."}</p>
              </div>
              {detail.log_tail && (
                <div className="rounded-2xl border border-hairline bg-surface p-4">
                  <div className="mb-2 text-xs font-medium text-ink-3">End of the MARBLE log</div>
                  <pre className="max-h-72 overflow-auto font-mono text-xs leading-5 whitespace-pre-wrap text-ink-2">{detail.log_tail}</pre>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
