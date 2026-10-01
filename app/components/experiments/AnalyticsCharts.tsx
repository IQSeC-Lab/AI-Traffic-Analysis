"use client";

import { useState } from "react";

import type { Analytics, CategoryStats } from "@/lib/api";
import { formatBytes, formatMs, formatNumber, formatPercent } from "@/lib/format";
import { BarList } from "@/components/charts/BarList";
import { ChartCard } from "@/components/charts/ChartCard";
import { GroupedColumns } from "@/components/charts/GroupedColumns";
import { Histogram } from "@/components/charts/Histogram";
import type { Series } from "@/components/charts/scale";

// Each chart is its own tile so the results page can arrange them in a bento grid.
// A chart draws one series per group of `data`: a run's variants (temperatures,
// models, network conditions), or the single group of a Data Collector run.

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
  { key: "median_duration_s", label: "Generation", format: (v) => `${formatNumber(v)} s` },
];

type TileProps = { data: Analytics; series: Series[]; height?: number; className?: string };

const share = (values: number[]) => {
  const total = values.reduce((a, b) => a + b, 0);
  return values.map((v) => (total ? v / total : 0));
};

const binLabel = (edges: number[], i: number, f: (v: number) => string) => `${f(edges[i])} – ${f(edges[i + 1])}`;

/** The groups in `data` that have a series, in series order, each with its series. */
function seriesGroups(data: Analytics, series: Series[]) {
  const byKey = new Map(data.groups.map((g) => [g.key, g]));
  return series.filter((s) => byKey.has(s.id)).map((s) => ({ group: byKey.get(s.id)!, series: s }));
}

export function GapChart({ data, series, height = 240, className }: TileProps) {
  const gapSeries = seriesGroups(data, series).map(({ group, series: s }) => ({
    ...s,
    values: share(data.gap_hist.series[group.key] ?? []),
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
  const groups = seriesGroups(data, series);
  const sizeSeries = groups.map(({ group, series: s }) => ({ ...s, values: share(data.size_hist.series[group.key] ?? []) }));
  const outside = groups.reduce((a, { group }) => a + (data.size_hist.outside?.[group.key] ?? 0), 0);
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

/** Medians per prompt category. With `byPrompt`, the categories are the run's own prompts ("Prompt 1", ...). */
export function CategoryChart({ data, series, height = 240, className, byPrompt = false }: TileProps & { byPrompt?: boolean }) {
  const [metric, setMetric] = useState<MetricKey>("median_ttft_ms");
  const groups = seriesGroups(data, series);
  const categories = [...new Set(groups.flatMap(({ group }) => group.by_category.map((c) => c.category)))];
  const m = METRICS.find((x) => x.key === metric)!;
  const categorySeries = groups.map(({ group, series: s }) => ({
    ...s,
    values: categories.map((c) => group.by_category.find((x) => x.category === c)?.[metric] ?? null),
  }));
  return (
    <ChartCard
      title={byPrompt ? "By prompt" : "By prompt category"}
      subtitle={`Median ${m.label.toLowerCase()} per ${byPrompt ? "prompt" : "category"}`}
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
        columns: [byPrompt ? "Prompt" : "Category", ...categorySeries.map((s) => s.label)],
        rows: categories.map((c, i) => [c, ...categorySeries.map((s) => (s.values[i] == null ? "—" : m.format(s.values[i]!)))]),
      }}
    >
      {categories.length > 0 && categorySeries.some((s) => s.values.some((v) => v != null)) ? (
        <GroupedColumns
          categories={categories}
          shortLabels={categories.map((c) => (byPrompt ? c.replace(/^Prompt /, "#") : (CATEGORY_SHORT[c] ?? c)))}
          series={categorySeries}
          height={height}
          format={m.format}
          ariaLabel={`Median ${m.label} by ${byPrompt ? "prompt" : "prompt category"}`}
        />
      ) : (
        <NoData height={height} text="No client timing for this metric. Runs record it from now on." />
      )}
    </ChartCard>
  );
}

/** One bar per group for a chosen metric, e.g. median first event per temperature. The table has every metric. */
export function CompareChart({
  data,
  series,
  variable,
  height = 200,
  className,
}: TileProps & { variable: string }) {
  const [metric, setMetric] = useState<MetricKey>("median_ttft_ms");
  const groups = seriesGroups(data, series);
  const m = METRICS.find((x) => x.key === metric)!;
  const noun = variable[0].toUpperCase() + variable.slice(1);
  return (
    <ChartCard
      title={`By ${variable}`}
      subtitle={`Median ${m.label.toLowerCase()} per ${variable}, over its captures`}
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
        columns: [noun, "Captures", ...METRICS.map((x) => x.label)],
        rows: groups.map(({ group, series: s }) => [
          s.label,
          group.summary.captures,
          ...METRICS.map((x) => (group.summary[x.key] == null ? "—" : x.format(group.summary[x.key]!))),
        ]),
      }}
    >
      {groups.some(({ group }) => group.summary[metric] != null) ? (
        <BarList
          rows={groups.map(({ group, series: s }) => ({ ...s, value: group.summary[metric], note: `${group.summary.captures} captures` }))}
          format={m.format}
          height={height}
          ariaLabel={`Median ${m.label} per ${variable}`}
        />
      ) : (
        <NoData height={height} text="No captures with this metric yet." />
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
