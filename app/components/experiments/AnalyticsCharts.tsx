"use client";

import { useState } from "react";

import type { Analytics, CategoryStats } from "@/lib/api";
import { formatBytes, formatMs, formatNumber, formatPercent } from "@/lib/format";
import { ChartCard } from "@/components/charts/ChartCard";
import { GroupedColumns } from "@/components/charts/GroupedColumns";
import { Histogram } from "@/components/charts/Histogram";
import type { Series } from "@/components/charts/scale";

// Each chart is its own tile so the results page can arrange them in a bento grid.

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

type TileProps = { data: Analytics; series: Series[]; height?: number; className?: string };

const share = (values: number[]) => {
  const total = values.reduce((a, b) => a + b, 0);
  return values.map((v) => (total ? v / total : 0));
};

const binLabel = (edges: number[], i: number, f: (v: number) => string) => `${f(edges[i])} – ${f(edges[i + 1])}`;

/** The runs in `data` that have a series, each with its series. */
function seriesRuns(data: Analytics, series: Series[]) {
  const byId = new Map(series.map((s) => [s.id, s]));
  return data.runs.filter((r) => byId.has(r.id)).map((r) => ({ run: r, series: byId.get(r.id)! }));
}

export function GapChart({ data, series, height = 240, className }: TileProps) {
  const gapSeries = seriesRuns(data, series).map(({ run, series: s }) => ({
    ...s,
    values: share(data.gap_hist.series[run.id] ?? []),
  }));
  return (
    <ChartCard
      title="Time between stream packets"
      subtitle="Server → client packets of the response stream · share of gaps, log scale"
      legend={gapSeries}
      height={height}
      className={className}
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
          height={height}
          formatX={formatMs}
          formatY={(v) => formatPercent(v, 0)}
          ariaLabel="Distribution of time between stream packets"
        />
      ) : (
        <NoData height={height} />
      )}
    </ChartCard>
  );
}

export function SizeChart({ data, series, height = 240, className }: TileProps) {
  const runs = seriesRuns(data, series);
  const sizeSeries = runs.map(({ run, series: s }) => ({ ...s, values: share(data.size_hist.series[run.id] ?? []) }));
  const outside = runs.reduce((a, { run }) => a + (data.size_hist.outside?.[run.id] ?? 0), 0);
  return (
    <ChartCard
      title="Stream packet sizes"
      subtitle="TCP payload of each server → client packet · share of packets"
      legend={sizeSeries}
      height={height}
      className={className}
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
          height={height}
          formatX={(v) => formatBytes(v)}
          formatY={(v) => formatPercent(v, 0)}
          ariaLabel="Distribution of stream packet sizes"
        />
      ) : (
        <NoData height={height} />
      )}
    </ChartCard>
  );
}

export function CategoryChart({ data, series, height = 240, className }: TileProps) {
  const [metric, setMetric] = useState<MetricKey>("median_ttft_ms");
  const runs = seriesRuns(data, series);
  const categories = [...new Set(runs.flatMap(({ run }) => run.by_category.map((c) => c.category)))];
  const m = METRICS.find((x) => x.key === metric)!;
  const categorySeries = runs.map(({ run, series: s }) => ({
    ...s,
    values: categories.map((c) => run.by_category.find((x) => x.category === c)?.[metric] ?? null),
  }));
  return (
    <ChartCard
      title="By prompt category"
      subtitle={`Median ${m.label.toLowerCase()} per category`}
      legend={categorySeries}
      legendShape="rect"
      height={height}
      className={className}
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
          height={height}
          format={m.format}
          ariaLabel={`Median ${m.label} by prompt category`}
        />
      ) : (
        <NoData height={height} text="No client timing for this metric. Runs record it from now on." />
      )}
    </ChartCard>
  );
}

function NoData({ text = "No packets captured yet.", height }: { text?: string; height: number }) {
  return (
    <div className="flex items-center justify-center text-sm text-ink-3" style={{ height }}>
      {text}
    </div>
  );
}
