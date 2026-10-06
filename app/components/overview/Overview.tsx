"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { api, isActive, type ModelsResponse, type Run, type SystemInfo } from "@/lib/api";
import { EXPERIMENTS, experimentHref, experimentName, runHref } from "@/lib/experiments";
import { formatBytes, timeAgo } from "@/lib/format";
import { useInterval } from "@/lib/useInterval";
import { ButtonLink, Card, LiveDot, ProgressBar, StatTile, StatusPill } from "@/components/ui";
import { RunBadge, runTitle } from "@/components/experiments/RunBadge";

export function Overview() {
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [models, setModels] = useState<ModelsResponse | null>(null);
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const refreshRuns = useCallback(() => {
    api<Run[]>("/experiments/runs")
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
        <p className="mt-1 text-sm text-ink-2">Runs, captures and the state of the experiment host.</p>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatTile label="Runs" value={runs ? runs.length : "—"} hint={runs ? `${runs.filter((r) => r.status === "completed").length} completed` : undefined} />
        <StatTile label="Captures" value={captures.toLocaleString()} hint="PCAP files" />
        <StatTile label="Traffic captured" value={formatBytes(captured)} />
        <StatTile label="Models ready" value={models ? ready.length : "—"} hint={models ? formatBytes(ready.reduce((a, m) => a + m.size_bytes, 0)) : undefined} />
      </div>

      {active.length > 0 ? (
        <div>
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
            <LiveDot /> In progress
          </h2>
          <div className="grid gap-4 md:grid-cols-2">
            {active.map((run) => (
              <Link
                key={run.id}
                href={runHref(run)}
                className="block rounded-2xl border border-hairline bg-surface p-5 shadow-[0_1px_2px_rgba(0,0,0,0.04)] transition-colors hover:border-axis"
              >
                <div className="flex items-start justify-between gap-3">
                  <RunBadge number={run.number} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold">{runTitle(run)}</div>
                    <div className="truncate text-xs text-ink-3">
                      {experimentName(run.experiment)} ·{" "}
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
                </div>
              </Link>
            ))}
          </div>
        </div>
      ) : runs === null ? null : (
        <div className="flex items-center justify-between gap-4 rounded-2xl border border-hairline bg-surface p-5 shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
          <div>
            <div className="text-sm font-semibold">No run in progress</div>
            <div className="mt-0.5 text-sm text-ink-2">
              Each capture runs in a fresh, isolated container. Docker is cleaned up when the run ends.
            </div>
          </div>
          <ButtonLink href="/experiments/data-collector/new">New run</ButtonLink>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[20rem_1fr]">
        <Card title="Host" description="The machine that runs the experiments.">
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium">Docker</div>
                <div className="text-xs text-ink-3">{system ? (system.docker.available ? `Engine ${system.docker.version}` : system.docker.error) : "…"}</div>
              </div>
              {system && (
                <span className="h-2 w-2 rounded-full" style={{ background: system.docker.available ? "var(--good)" : "var(--critical)" }} />
              )}
            </div>
            {system && system.gpus.length === 0 && (
              <div>
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
              <span className="flex-1 text-sm">Models</span>
              <span className="text-xs text-ink-3">{ready.length} ready</span>
            </Link>
          </div>
        </Card>

        <Card title="Recent runs" description="Of every experiment. Each experiment's page lists all its runs." padded={false}>
          {runs && runs.length === 0 && <p className="px-5 pb-5 text-sm text-ink-3">No runs yet.</p>}
          <ul className="divide-y divide-[var(--hairline)]">
            {runs?.slice(0, 5).map((r) => (
              <li key={r.id}>
                <Link href={runHref(r)} className="flex items-center gap-3 px-5 py-3 hover:bg-surface-2/60">
                  <RunBadge number={r.number} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{runTitle(r)}</div>
                    <div className="text-xs text-ink-3">
                      {experimentName(r.experiment)} · {r.progress.completed}/{r.progress.total} captures ·{" "}
                      {timeAgo(r.created_at, now)}
                    </div>
                  </div>
                  <StatusPill status={r.status} />
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <Card title="Experiments" description="The five MaLLM experiments, and one you set up yourself." padded={false}>
        <ul className="divide-y divide-[var(--hairline)] border-t border-hairline">
          {EXPERIMENTS.map(({ slug, name, summary, description, available }) => {
            const body = (
              <>
                <div className="w-48 shrink-0">
                  <div className="text-sm font-medium">{name}</div>
                  <div className="text-xs text-ink-3">{summary}</div>
                </div>
                <p className="min-w-0 flex-1 text-sm text-ink-2">{description}</p>
                <span className={`w-24 shrink-0 text-right text-xs ${available ? "font-medium text-accent" : "text-ink-3"}`}>
                  {available ? "Open" : "Not yet"}
                </span>
              </>
            );
            return (
              <li key={slug}>
                {available ? (
                  <Link href={experimentHref(slug)} className="flex items-start gap-6 px-5 py-3.5 hover:bg-surface-2/60">
                    {body}
                  </Link>
                ) : (
                  <div className="flex items-start gap-6 px-5 py-3.5">{body}</div>
                )}
              </li>
            );
          })}
        </ul>
      </Card>
    </div>
  );
}

