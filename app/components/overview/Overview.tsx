"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ArrowRight, Box, Container, Cpu, Database, FlaskConical, HardDrive, Layers, Play } from "lucide-react";

import { api, isActive, type ModelsResponse, type Run, type SystemInfo } from "@/lib/api";
import { EXPERIMENTS, experimentHref, runHref } from "@/lib/experiments";
import { formatBytes, timeAgo } from "@/lib/format";
import { useInterval } from "@/lib/useInterval";
import { Card, LiveDot, ProgressBar, StatTile, StatusPill } from "@/components/ui";
import { RunBadge, runTitle } from "@/components/experiments/RunBadge";

export function Overview() {
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [models, setModels] = useState<ModelsResponse | null>(null);
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const refreshRuns = useCallback(() => {
    api<Run[]>("/data-collector/runs")
      .then((r) => {
        setRuns(r);
        setNow(Date.now());
      })
      .catch(() => setRuns([]));
  }, []);

  useEffect(() => {
    api<SystemInfo>("/system").then(setSystem).catch(() => {});
    api<ModelsResponse>("/settings/models").then(setModels).catch(() => {});
    refreshRuns();
  }, [refreshRuns]);

  const active = runs?.filter(isActive) ?? [];
  useInterval(refreshRuns, active.length > 0 ? 3000 : null);

  const ready = models?.models.filter((m) => m.complete) ?? [];
  const captures = runs?.reduce((a, r) => a + r.outputs.pcaps, 0) ?? 0;
  const captured = runs?.reduce((a, r) => a + r.outputs.pcap_bytes, 0) ?? 0;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Overview</h1>
        <p className="mt-1 text-sm text-ink-2">Run LLM traffic experiments and see what the network reveals about each model.</p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="Runs" value={runs ? runs.length : "—"} hint={runs ? `${runs.filter((r) => r.status === "completed").length} completed` : undefined} icon={FlaskConical} />
        <StatTile label="Captures" value={captures.toLocaleString()} hint="PCAP files" icon={Layers} />
        <StatTile label="Traffic captured" value={formatBytes(captured)} icon={HardDrive} />
        <StatTile label="Models ready" value={models ? ready.length : "—"} hint={models ? formatBytes(ready.reduce((a, m) => a + m.size_bytes, 0)) : undefined} icon={Box} />
      </div>

      {active.length > 0 ? (
        <div>
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
            <LiveDot /> In progress
          </h2>
          <div className="grid gap-3 md:grid-cols-2">
            {active.map((run) => (
              <Link
                key={run.id}
                href={runHref(run.id)}
                className="group block rounded-2xl border border-accent/30 bg-surface p-5 shadow-[0_1px_2px_rgba(0,0,0,0.04)] ring-4 ring-accent/5 transition-colors hover:border-accent/60"
              >
                <div className="flex items-start justify-between gap-3">
                  <RunBadge number={run.number} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold">{runTitle(run)}</div>
                    <div className="truncate text-xs text-ink-3">
                      {run.status === "queued" ? run.queue?.reason ?? "Waiting in the queue" : run.step ?? "Starting…"}
                    </div>
                  </div>
                  <StatusPill status={run.status} />
                </div>
                <div className="mt-4 flex items-center gap-3 text-xs text-ink-3 tabular-nums">
                  <ProgressBar value={run.progress.completed} max={run.progress.total} />
                  <span className="shrink-0">
                    {run.progress.completed} / {run.progress.total}
                  </span>
                  <ArrowRight className="h-4 w-4 shrink-0 transition-transform group-hover:translate-x-0.5 group-hover:text-accent" />
                </div>
              </Link>
            ))}
          </div>
        </div>
      ) : runs === null ? null : (
        <div
          className="flex flex-wrap items-center justify-between gap-4 rounded-2xl p-6 text-white shadow-sm"
          style={{ background: "var(--brand-gradient)" }}
        >
          <div>
            <div className="text-lg font-semibold">Ready for a new experiment</div>
            <div className="mt-1 max-w-xl text-sm text-white/80">
              Pick a model and prompts. Every capture runs in a fresh, isolated container, and Docker is left clean afterwards.
            </div>
          </div>
          <Link
            href="/experiments/data-collector/new"
            className="inline-flex h-9 items-center gap-2 rounded-lg bg-white px-4 text-sm font-medium text-accent-strong shadow-sm hover:bg-white/90"
          >
            <Play className="h-4 w-4" /> Start a run
          </Link>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[20rem_1fr]">
        <Card title="Host" description="The machine that runs the experiments.">
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-surface-2">
                <Container className="h-4 w-4 text-ink-2" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium">Docker</div>
                <div className="text-xs text-ink-3">{system ? (system.docker.available ? `Engine ${system.docker.version}` : system.docker.error) : "…"}</div>
              </div>
              {system && (
                <span className="h-2 w-2 rounded-full" style={{ background: system.docker.available ? "var(--good)" : "var(--critical)" }} />
              )}
            </div>
            {system && system.gpus.length === 0 && (
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-surface-2">
                  <Cpu className="h-4 w-4 text-ink-2" />
                </div>
                <div>
                  <div className="text-sm font-medium">No NVIDIA GPU</div>
                  <div className="text-xs text-ink-3">Models run on the CPU</div>
                </div>
              </div>
            )}
            {system?.gpus.map((gpu) => {
              const used = gpu.memory_used_mb != null && gpu.memory_total_mb ? gpu.memory_used_mb / gpu.memory_total_mb : 0;
              return (
                <div key={gpu.index}>
                  <div className="flex items-baseline justify-between gap-2 text-sm">
                    <span className="font-medium">GPU {gpu.index}</span>
                    <span className="text-xs text-ink-3 tabular-nums">{gpu.utilization_pct ?? "—"}% busy</span>
                  </div>
                  <div className="truncate text-xs text-ink-3">{gpu.name}</div>
                  <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-accent-wash">
                    <div className="h-full rounded-full bg-accent" style={{ width: `${used * 100}%` }} />
                  </div>
                  <div className="mt-1 text-[11px] text-ink-3 tabular-nums">
                    {gpu.memory_used_mb != null && gpu.memory_total_mb != null
                      ? `${(gpu.memory_used_mb / 1024).toFixed(1)} of ${(gpu.memory_total_mb / 1024).toFixed(0)} GB memory`
                      : "Memory unknown"}
                  </div>
                </div>
              );
            })}
            <Link href="/settings#models" className="flex items-center gap-3 rounded-lg border border-hairline p-2.5 hover:bg-surface-2">
              <Database className="h-4 w-4 text-ink-3" />
              <span className="flex-1 text-sm">Models</span>
              <span className="text-xs text-ink-3">{ready.length} ready</span>
            </Link>
          </div>
        </Card>

        <Card
          title="Recent runs"
          action={
            <Link href={experimentHref("data-collector")} className="text-xs font-medium text-accent hover:underline">
              View all
            </Link>
          }
          padded={false}
        >
          {runs && runs.length === 0 && <p className="px-5 pb-5 text-sm text-ink-3">No runs yet.</p>}
          <ul className="divide-y divide-[var(--hairline)]">
            {runs?.slice(0, 5).map((r) => (
              <li key={r.id}>
                <Link href={runHref(r.id)} className="flex items-center gap-3 px-5 py-3 hover:bg-surface-2/60">
                  <RunBadge number={r.number} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{runTitle(r)}</div>
                    <div className="text-xs text-ink-3">
                      Data Collector · {r.progress.completed}/{r.progress.total} captures · {timeAgo(r.created_at, now)}
                    </div>
                  </div>
                  <StatusPill status={r.status} />
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <div>
        <h2 className="mb-3 text-sm font-semibold">Experiments</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {EXPERIMENTS.map(({ slug, name, summary, description, icon: Icon, available }) => {
            const body = (
              <>
                <div className="flex items-center justify-between">
                  <div className={`flex h-10 w-10 items-center justify-center rounded-xl ${available ? "bg-accent-wash text-accent" : "bg-surface-2 text-ink-3"}`}>
                    <Icon className="h-5 w-5" strokeWidth={1.75} />
                  </div>
                  {available ? (
                    <ArrowRight className="h-4 w-4 text-ink-3 transition-transform group-hover:translate-x-0.5 group-hover:text-accent" />
                  ) : (
                    <span className="rounded-md bg-surface-2 px-1.5 py-0.5 text-[10px] font-medium text-ink-3">Coming soon</span>
                  )}
                </div>
                <div className="mt-4 text-sm font-semibold">{name}</div>
                <div className="text-xs font-medium text-ink-3">{summary}</div>
                <p className="mt-2 text-sm text-ink-2">{description}</p>
              </>
            );
            return available ? (
              <Link
                key={slug}
                href={experimentHref(slug)}
                className="group rounded-2xl border border-hairline bg-surface p-5 shadow-[0_1px_2px_rgba(0,0,0,0.04)] transition-all hover:-translate-y-0.5 hover:shadow-md"
              >
                {body}
              </Link>
            ) : (
              <div key={slug} className="rounded-2xl border border-dashed border-hairline p-5 opacity-80">
                {body}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

