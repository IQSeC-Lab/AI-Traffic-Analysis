"use client";

import { useState } from "react";

import type { Analytics, CategoryStats } from "@/lib/api";
import { formatBytes, formatMs, formatNumber, formatPercent } from "@/lib/format";
import { ChartCard } from "@/components/charts/ChartCard";
import { GroupedColumns } from "@/components/charts/GroupedColumns";
import { Histogram } from "@/components/charts/Histogram";
import type { Series } from "@/components/charts/scale";

const CATEGORY_SHORT: Record<string, string> = {
  "Text Summarization": "Summaries",
  "Code Generation": "Code",
  "Math / Algorithmic Reasoning": "Math",
  "Malware / Adversarial": "Adversarial",
  "Logical Reasoning & Puzzles": "Logic",
  "Technical Explanation": "Technical",
};

type MetricKey = Exclude<keyof CategoryStats, "category" | "captures" | "total_bytes">;

const METRICS: { key: MetricKey; label: string; format: (v: number) => string }[] = [
  { key: "median_ttft_ms", label: "First event", format: formatMs },
  { key: "median_events_per_s", label: "Events/s", format: (v) => `${formatNumber(v)}/s` },
  { key: "median_gap_ms", label: "Packet gap", format: formatMs },
  { key: "median_stream_packets", label: "Packets", format: (v) => formatNumber(v, 0) },
  { key: "median_packet_bytes", label: "Packet size", format: (v) => `${formatNumber(v, 0)} B` },
  { key: "median_response_chars", label: "Response", format: (v) => `${formatNumber(v, 0)} chars` },
];

const share = (values: number[]) => {
  const total = values.reduce((a, b) => a + b, 0);
  return values.map((v) => (total ? v / total : 0));
};

export function AnalyticsCharts({ data, series }: { data: Analytics; series: Series[] }) {
  const [metric, setMetric] = useState<MetricKey>("median_ttft_ms");
  const byId = new Map(series.map((s) => [s.id, s]));
  const runs = data.runs.filter((r) => byId.has(r.id));
  const gapSeries = runs.map((r) => ({ ...byId.get(r.id)!, values: share(data.gap_hist.series[r.id] ?? []) }));
  const sizeSeries = runs.map((r) => ({ ...byId.get(r.id)!, values: share(data.size_hist.series[r.id] ?? []) }));
  const categories = [...new Set(runs.flatMap((r) => r.by_category.map((c) => c.category)))];
  const m = METRICS.find((x) => x.key === metric)!;
  const categorySeries = runs.map((r) => ({
    ...byId.get(r.id)!,
    values: categories.map((c) => r.by_category.find((x) => x.category === c)?.[metric] ?? null),
  }));
  const outside = runs.reduce((a, r) => a + (data.size_hist.outside?.[r.id] ?? 0), 0);

  const binLabel = (edges: number[], i: number, f: (v: number) => string) => `${f(edges[i])} – ${f(edges[i + 1])}`;

  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <ChartCard
        title="Time between stream packets"
        subtitle="Server → client packets of the response stream · share of gaps, log scale"
        legend={gapSeries}
        table={{
          columns: ["Gap", ...gapSeries.map((s) => s.label)],
          rows: data.gap_hist.edges.slice(0, -1).map((_, i) => [
            binLabel(data.gap_hist.edges, i, formatMs),
            ...gapSeries.map((s) => formatPercent(s.values[i])),
          ]),
        }}
      >
        {data.gap_hist.edges.length > 1 ? (
          <Histogram
            edges={data.gap_hist.edges}
            series={gapSeries}
            log
            formatX={formatMs}
            formatY={(v) => formatPercent(v, 0)}
            ariaLabel="Distribution of time between stream packets"
          />
        ) : (
          <NoData />
        )}
      </ChartCard>

      <ChartCard
        title="Stream packet sizes"
        subtitle="TCP payload of each server → client packet · share of packets"
        legend={sizeSeries}
        footer={outside > 0 ? `${outside.toLocaleString()} outlier packets outside the central 99% are not shown.` : undefined}
        table={{
          columns: ["Payload", ...sizeSeries.map((s) => s.label)],
          rows: data.size_hist.edges.slice(0, -1).map((_, i) => [
            binLabel(data.size_hist.edges, i, (v) => `${v} B`),
            ...sizeSeries.map((s) => formatPercent(s.values[i])),
          ]),
        }}
      >
        {data.size_hist.edges.length > 1 ? (
          <Histogram
            edges={data.size_hist.edges}
            series={sizeSeries}
            formatX={(v) => formatBytes(v)}
            formatY={(v) => formatPercent(v, 0)}
            ariaLabel="Distribution of stream packet sizes"
          />
        ) : (
          <NoData />
        )}
      </ChartCard>

      <div className="xl:col-span-2">
        <ChartCard
          title="By prompt category"
          subtitle={`Median ${m.label.toLowerCase()} per category`}
          legend={categorySeries}
          legendShape="rect"
          controls={
            <select
              value={metric}
              onChange={(e) => setMetric(e.target.value as MetricKey)}
              className="h-7 rounded-lg border border-hairline bg-surface px-2 text-xs font-medium outline-none"
              aria-label="Metric"
            >
              {METRICS.map((x) => (
                <option key={x.key} value={x.key}>
                  {x.label}
                </option>
              ))}
            </select>
          }
          table={{
            columns: ["Category", ...categorySeries.map((s) => s.label)],
            rows: categories.map((c, i) => [c, ...categorySeries.map((s) => (s.values[i] == null ? "—" : m.format(s.values[i]!)))]),
          }}
        >
          {categories.length > 0 && categorySeries.some((s) => s.values.some((v) => v != null)) ? (
            <GroupedColumns
              categories={categories}
              shortLabels={categories.map((c) => CATEGORY_SHORT[c] ?? c)}
              series={categorySeries}
              format={m.format}
              ariaLabel={`Median ${m.label} by prompt category`}
            />
          ) : (
            <NoData text="No client timing for this metric. Runs record it from now on." />
          )}
        </ChartCard>
      </div>
    </div>
  );
}

function NoData({ text = "No packets captured yet." }: { text?: string }) {
  return <div className="flex h-60 items-center justify-center text-sm text-ink-3">{text}</div>;
}
