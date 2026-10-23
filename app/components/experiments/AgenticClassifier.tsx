"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { api, type AgenticCapture, type AgenticMetrics, type ClassifierResult, type Run } from "@/lib/api";
import { EXPERIMENTS } from "@/lib/experiments";
import { formatBytes, formatMs, formatNumber, formatPercent } from "@/lib/format";
import { useInterval } from "@/lib/useInterval";
import { Segmented, Spinner, buttonClass } from "@/components/ui";
import { BarList } from "@/components/charts/BarList";
import { BoxPlot, boxOf } from "@/components/charts/BoxPlot";
import { ChartCard } from "@/components/charts/ChartCard";
import { GroupedColumns } from "@/components/charts/GroupedColumns";
import type { Series } from "@/components/charts/scale";

const count = (v: number) => formatNumber(v, 0);
const percent = (v: number) => formatPercent(v, 0);
const percent1 = (v: number) => formatPercent(v, 1);
const capital = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

// 1, 10 and 100 of each unit up to 100 GB: a tenfold step apart (nearly, between units) and round in the unit they are shown in
const BYTE_TICKS = [0, 1, 2, 3].flatMap((unit) => [1, 10, 100].map((n) => n * 1024 ** unit));

// Sizes, durations and counts spread over orders of magnitude between categories: a log axis, as in the dataset's figure
const DISTRIBUTIONS: { key: keyof AgenticMetrics; label: string; format: (v: number) => string; log: boolean; ticks?: number[] }[] = [
  { key: "total_bytes", label: "Bytes", format: (v) => formatBytes(v), log: true, ticks: BYTE_TICKS },
  { key: "task_duration", label: "Duration", format: (v) => `${formatNumber(v)} s`, log: true },
  { key: "total_packets", label: "Packets", format: count, log: true },
  { key: "packets_per_second", label: "Packet rate", format: (v) => `${formatNumber(v)}/s`, log: true },
  { key: "total_bursts", label: "Bursts", format: count, log: true },
  { key: "idle_time_fraction", label: "Idle time", format: percent, log: false },
  { key: "median_gap_ms", label: "Packet gap", format: formatMs, log: true },
];

const median = (values: number[]) => {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = sorted.length >> 1;
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
};

/** The dataset's traffic distributions figure: per task category and topology, how a measurement spreads over the tasks. */
export function DistributionTile({
  captures,
  series,
  callLabel,
  height = 260,
  className,
}: {
  captures: AgenticCapture[];
  series: Series[];
  callLabel: string;
  height?: number;
  className?: string;
}) {
  const metrics = useMemo(() => [...DISTRIBUTIONS, { key: "calls" as const, label: callLabel, format: count, log: true, ticks: undefined }], [callLabel]);
  const [metric, setMetric] = useState<keyof AgenticMetrics>(metrics[0].key);
  const m = metrics.find((x) => x.key === metric)!;

  const { categories, boxSeries } = useMemo(() => {
    // A task counts once per topology: the median of its repetitions
    const byTask = new Map<string, number[]>();
    const categories: string[] = [];
    for (const c of captures) {
      const v = c.metrics[metric];
      if (c.status !== "completed" || v == null || c.category == null) continue;
      if (!categories.includes(c.category)) categories.push(c.category);
      const key = `${c.variant}\n${c.category}\n${c.prompt}`;
      byTask.set(key, [...(byTask.get(key) ?? []), v]);
    }
    const boxSeries = series.map((s) => ({
      ...s,
      boxes: categories.map((category) =>
        boxOf([...byTask].filter(([key]) => key.startsWith(`${s.id}\n${category}\n`)).map(([, values]) => median(values))),
      ),
    }));
    return { categories, boxSeries };
  }, [captures, series, metric]);

  return (
    <ChartCard
      title="By task category"
      subtitle={`${m.label} per task: the box holds the middle half of a category's tasks, the line across it is their median, the whiskers reach the others. A task counts once, by the median of its repetitions.`}
      legend={boxSeries}
      legendShape="rect"
      height={height}
      className={className}
      controls={
        <select
          value={metric}
          onChange={(e) => setMetric(e.target.value as keyof AgenticMetrics)}
          className="h-7 rounded-lg border border-hairline bg-surface px-2 text-xs font-medium outline-none"
          aria-label="Metric"
        >
          {metrics.map((x) => (
            <option key={x.key} value={x.key}>
              {x.label}
            </option>
          ))}
        </select>
      }
      table={{
        columns: ["Category", "Topology", "Tasks", "Lowest", "First quartile", "Median", "Third quartile", "Highest"],
        rows: categories.flatMap((category, i) =>
          boxSeries.flatMap((s) => {
            const b = s.boxes[i];
            return b ? [[category, s.label, b.n, ...[b.low, b.q1, b.median, b.q3, b.high].map(m.format)]] : [];
          }),
        ),
      }}
    >
      {categories.length > 0 ? (
        <BoxPlot categories={categories} series={boxSeries} format={m.format} log={m.log} ticks={m.ticks} height={height} ariaLabel={`${m.label} per task, by task category and topology`} />
      ) : (
        <div className="flex items-center justify-center text-sm text-ink-3" style={{ height }}>
          No completed task yet.
        </div>
      )}
    </ChartCard>
  );
}

/** What the forests predict: the task's or prompt's category, or (user-to-LLM runs) which variant made the capture. */
export type ClassifierTarget = "category" | "variant";

const STATE_TITLE: Record<Exclude<ClassifierResult["status"], "ready">, string> = {
  running: "Trained when the run has finished",
  unavailable: "Not installed on the server",
  missing: "Not calculated yet",
  too_small: "Not enough to train on",
  failed: "The classifier could not be trained",
  waiting: "Waiting for other runs",
  computing: "Training",
};

/**
 * The classifier side of the dataset's analysis, on this run: whether the task category can be told from the
 * encrypted traffic, within a topology and across them, with only some agents visible, and from which measurements.
 * On a user-to-LLM run the same forests predict the prompt's category, with the run's variants in the topologies' place,
 * or (target "variant") which variant made the capture: model fingerprinting on a Scalability run.
 */
export function ClassifierTiles({
  run,
  series,
  live,
  targets = ["category"],
}: {
  run: Run;
  series: Series[];
  live: boolean;
  targets?: ClassifierTarget[]; // what the forests can predict on this run, the first shown first
}) {
  const experiment = EXPERIMENTS.find((e) => e.slug === run.experiment);
  const agentic = Boolean(experiment?.agentic);
  const unit = agentic ? "task" : "prompt";
  const variable = experiment?.variable; // what the run compares; none in the Data Collector
  const what = variable?.one ?? "setting";
  const whatMany = variable?.many ?? "settings";
  const [target, setTarget] = useState<ClassifierTarget>(targets[0]);
  const byVariant = target === "variant";
  const title = agentic ? "Task fingerprinting" : byVariant ? `${capital(what)} fingerprinting` : "Prompt fingerprinting";
  // Per target, so switching back is instant and a late answer never lands under the other one
  const [results, setResults] = useState<Partial<Record<ClassifierTarget, ClassifierResult>>>({});
  const result = results[target];
  const base = `/${run.experiment}/runs/${run.id}/classifier`;
  const load = useCallback(
    (t: ClassifierTarget) => {
      const save = (found: ClassifierResult) => setResults((all) => ({ ...all, [t]: found }));
      api<ClassifierResult>(`${base}?target=${t}`)
        .then(save)
        .catch((e: Error) => save({ status: "failed", reason: e.message }));
    },
    [base],
  );
  // Every target at once: asking is what starts a target's forests on the server, so a switch never waits for them to begin
  const all = targets.join(",");
  useEffect(() => all.split(",").forEach((t) => load(t as ClassifierTarget)), [load, all, live]);
  const pending = result?.status === "computing" || result?.status === "waiting";
  useInterval(() => load(target), pending ? 3000 : null);

  // Runs that complete are trained on their own; older ones (and failed trainings) when asked, every target at once
  const [starting, setStarting] = useState(false);
  const calculate = () => {
    setStarting(true);
    api(base, { method: "POST" })
      .then(() => all.split(",").forEach((t) => load(t as ClassifierTarget)))
      .catch((e: Error) => setResults((found) => ({ ...found, [target]: { status: "failed", reason: e.message } })))
      .finally(() => setStarting(false));
  };

  // It changes both tiles, so it sits above them
  const picker =
    targets.length > 1 ? (
      <div className="col-span-12 flex items-center gap-2 text-xs text-ink-3">
        The classifier predicts
        <Segmented
          value={target}
          onChange={(t) => {
            setTarget(t);
            load(t); // what it shows may be a step that has moved on
          }}
          options={targets.map((t) => ({ value: t, label: t === "variant" ? capital(what) : "Prompt category" }))}
        />
      </div>
    ) : null;

  if (!result) return null;
  if (result.status !== "ready") {
    return (
      <>
        {picker}
        <div className="col-span-12 rounded-2xl border border-hairline bg-surface p-5 shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
          <div className="text-sm font-semibold">{title}</div>
          <div className="mt-0.5 text-xs text-ink-3">
            {agentic
              ? "Whether a classifier can tell the task category from the encrypted traffic alone, on tasks it has not seen."
              : byVariant
                ? `Whether a classifier can tell which ${what} made a capture from the sizes and timing of its packets alone, on prompts it has not seen.`
                : "Whether a classifier can tell a prompt's category from the sizes and timing of its packets alone, on prompts it has not seen."}
          </div>
          <div className="mt-4 flex items-center gap-2 text-sm font-medium">
            {pending && <Spinner />}
            {STATE_TITLE[result.status]}
          </div>
          <p className="mt-1 max-w-3xl text-sm text-ink-2">{"step" in result ? `${result.step}…` : result.reason}</p>
          {(result.status === "missing" || result.status === "failed") && (
            <button type="button" onClick={calculate} disabled={starting} className={`mt-4 ${buttonClass("primary", "sm")}`}>
              {starting && <Spinner />}
              {result.status === "failed" ? "Calculate again" : "Calculate"}
            </button>
          )}
        </div>
      </>
    );
  }

  const colorOf = (key: string) => series.find((s) => s.id === key)?.color ?? "var(--accent)";
  const chance = { value: result.chance, label: `chance ${percent(result.chance)}` };
  const setup = `${result.folds} folds split by ${unit}`;

  // Trained on each topology: tested on its own held-out tasks, and on the same tasks under the other topologies
  const trained = [...new Set(result.transfer.map((t) => t.train))];
  const same = variable && !byVariant ? `Same ${variable.one}` : `Held-out ${unit}s`;
  // Telling the variants apart is one forest over all of them
  const forestLabel = (label: string) => (byVariant ? `All ${whatMany}` : label);
  const conditions = result.transfer.some((t) => !t.within) ? [same, `Another ${variable?.one}`] : [same];
  // Agentic runs put agent visibility beside it; a user-to-LLM run with one variant, the importances
  const single = !agentic && result.importance.length === 1;
  const transferSeries = trained.map((key) => {
    const mine = result.transfer.filter((t) => t.train === key);
    const cells = conditions.map((_, i) => mine.filter((t) => t.within === (i === 0)));
    const mean = (values: number[]) => (values.length ? values.reduce((a, b) => a + b, 0) / values.length : null);
    return {
      id: key,
      label: byVariant ? forestLabel(mine[0].train_label) : `Trained on ${mine[0].train_label}`,
      color: colorOf(key),
      values: cells.map((found) => mean(found.map((t) => t.mean))),
      spreads: cells.map((found) => mean(found.map((t) => t.std))),
    };
  });

  const agentCounts = [...new Set(result.visibility.flatMap((v) => v.counts.map((c) => c.agents)))].sort((a, b) => a - b);
  const visibilitySeries = result.visibility.map((v) => ({
    id: v.key,
    label: v.label,
    color: colorOf(v.key),
    values: agentCounts.map((k) => v.counts.find((c) => c.agents === k)?.mean ?? null),
    spreads: agentCounts.map((k) => v.counts.find((c) => c.agents === k)?.std ?? null),
  }));

  return (
    <>
      {picker}
      <ChartCard
        title={title}
        subtitle={`Balanced accuracy of a Random Forest predicting the ${byVariant ? what : `${unit} category`} from ${result.features} measurements of a capture's packets, tested on ${unit}s it has not seen (${setup}). Whiskers: one standard deviation over the folds.`}
        legend={transferSeries}
        legendShape="rect"
        height={240}
        className={agentic || single ? "col-span-5" : "col-span-12"}
        table={{
          columns: ["Trained on", "Tested on", "Accuracy", "Std. deviation", "Per fold"],
          rows: result.transfer.map((t) => [forestLabel(t.train_label), forestLabel(t.test_label), percent1(t.mean), percent1(t.std), t.values.map(percent).join(", ")]),
        }}
        footer={
          byVariant
            ? `${result.tasks} prompts, ${result.categories.length} ${whatMany}, ${Object.values(result.captures).reduce((a, b) => a + b, 0)} captures. Trained in ${formatNumber(result.seconds)} s.`
            : `${result.tasks} ${unit}s in ${result.categories.length} categories, ${Object.entries(result.captures)
                .map(([label, n]) => `${n} captures under ${label}`)
                .join(" and ")}. Trained in ${formatNumber(result.seconds)} s.`
        }
      >
        <GroupedColumns
          categories={conditions}
          series={transferSeries}
          format={percent}
          max={1}
          reference={chance}
          height={240}
          ariaLabel={
            byVariant
              ? `Balanced accuracy telling the ${whatMany} apart on held-out prompts`
              : variable
                ? `Balanced accuracy within and across ${variable.many}`
                : `Balanced accuracy on held-out ${unit}s`
          }
        />
      </ChartCard>

      {agentic && <ChartCard
        title="Agent visibility"
        subtitle={`The same accuracy when only some agents' packets are seen: that many agents picked at random in each task (${result.orderings} draws), trained and tested on that view.`}
        legend={visibilitySeries}
        legendShape="rect"
        height={240}
        className="col-span-7"
        table={{
          columns: ["Topology", "Agents seen", "Seen on average", "Accuracy", "Std. deviation"],
          rows: result.visibility.flatMap((v) => v.counts.map((c) => [v.label, c.agents, formatNumber(c.visible), percent1(c.mean), percent1(c.std)])),
        }}
        footer="A task with fewer agents than the number asked for shows all of its agents. Packets outside every agent's calls are never seen."
      >
        {visibilitySeries.length > 0 ? (
          <GroupedColumns
            categories={agentCounts.map((k) => `${k} agent${k === 1 ? "" : "s"}`)}
            series={visibilitySeries}
            format={percent}
            max={1}
            reference={chance}
            height={240}
            ariaLabel="Balanced accuracy by number of agents seen"
          />
        ) : (
          <div className="flex h-60 items-center justify-center text-sm text-ink-3">No packets could be attributed to an agent in this run.</div>
        )}
      </ChartCard>}

      <ChartCard
        title="What the classifier relies on"
        subtitle={`The ten measurements, of ${result.features}, that the forests lean on most${variable && !byVariant ? ` under each ${variable.one}` : ""}: their share of the forests' decisions (mean decrease in impurity), averaged over the folds.${agentic || byVariant ? "" : " Outgoing packets are the request, so their sizes follow the prompt's length."}`}
        height={300}
        className={single ? "col-span-7" : "col-span-12"}
        table={{
          columns: [byVariant ? "Trained on" : variable ? capital(variable.one) : "Model", "Rank", "Measurement", "Importance", "Lowest fold", "Highest fold"],
          rows: result.importance.flatMap((t) => t.features.map((f, i) => [forestLabel(t.label), i + 1, f.name, percent1(f.mean), percent1(f.min), percent1(f.max)])),
        }}
      >
        <div className="grid gap-8" style={{ gridTemplateColumns: `repeat(${Math.min(result.importance.length, 4)}, minmax(0, 1fr))` }}>
          {result.importance.map((t) => (
            <div key={t.key} className="min-w-0">
              <div className="mb-1 text-xs font-medium text-ink-2">{forestLabel(t.label)}</div>
              <BarList
                rows={t.features.map((f) => ({
                  id: f.name,
                  label: f.name,
                  color: colorOf(t.key),
                  value: f.mean,
                  note: `between ${percent1(f.min)} and ${percent1(f.max)} over the folds`,
                }))}
                format={percent1}
                height={280}
                ariaLabel={`The ten most important measurements for ${forestLabel(t.label)}`}
              />
            </div>
          ))}
        </div>
      </ChartCard>
    </>
  );
}
