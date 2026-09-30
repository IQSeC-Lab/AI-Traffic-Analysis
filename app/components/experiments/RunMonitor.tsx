"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Check } from "lucide-react";

import { api, isActive, type CurrentCapture, type Run, type RunLogs, type RunWorker } from "@/lib/api";
import { EXPERIMENTS } from "@/lib/experiments";
import { formatBytes, formatDuration, hardwareLabel } from "@/lib/format";
import { useInterval } from "@/lib/useInterval";
import { Card, ProgressBar, Spinner, StatTile } from "@/components/ui";
import { variantColor, variantLabel } from "./RunBadge";

const MAX_LOG_LINES = 2000;
const PHASES = ["Setup", "Prompts", "Cleanup", "Done"];

function phaseIndex(run: Run) {
  if (run.status === "cleaning_up") return 2;
  if (!isActive(run)) return 3;
  return run.current ? 1 : 0;
}

export function RunMonitor({ run, now }: { run: Run; now: number }) {
  const active = isActive(run);
  const [lines, setLines] = useState<string[]>([]);
  const cursor = useRef(0);
  const fetching = useRef(false);
  const logBox = useRef<HTMLDivElement>(null);
  const follow = useRef(true);

  const refreshLogs = useCallback(() => {
    if (fetching.current) return;
    fetching.current = true;
    api<RunLogs>(`/${run.experiment}/runs/${run.id}/logs?after=${cursor.current}`)
      .then(({ lines: fresh, next }) => {
        cursor.current = next;
        if (fresh.length > 0) setLines((prev) => [...prev, ...fresh].slice(-MAX_LOG_LINES));
      })
      .catch(() => {})
      .finally(() => {
        fetching.current = false;
      });
  }, [run.experiment, run.id]);

  // Runs again when the run finishes, to pick up its last lines.
  useEffect(refreshLogs, [refreshLogs, active]);
  useInterval(refreshLogs, active ? 1500 : null);

  useEffect(() => {
    const box = logBox.current;
    if (box && follow.current) box.scrollTop = box.scrollHeight;
  }, [lines]);

  const { completed, total } = run.progress;
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0;
  // Time is measured from when it left the queue
  const started = new Date(run.started_at ?? run.created_at).getTime();
  const end = run.finished_at ? new Date(run.finished_at).getTime() : now;
  const eta = active && completed > 0 ? ((end - started) / completed) * (total - completed) : null;
  const phase = phaseIndex(run);
  const workers = run.workers ?? [];
  const variable = EXPERIMENTS.find((e) => e.slug === run.experiment)?.variable;

  return (
    <div className="space-y-6">
      {run.status === "queued" && (
        <div className="rounded-2xl border border-hairline bg-surface p-5 shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
          <div>
            <div className="text-sm font-semibold">
              Waiting in the queue{run.queue?.position ? ` · #${run.queue.position}` : ""}
            </div>
            <p className="mt-0.5 text-sm text-ink-2">{run.queue?.reason ?? "Waiting for hardware to free up."}</p>
            <p className="mt-1 text-xs text-ink-3">
              It starts on its own as soon as there is room. You can cancel it meanwhile.
            </p>
          </div>
        </div>
      )}

      <div className="grid grid-cols-12 gap-4">
        <Card className="col-span-8">
          <div className="grid gap-6 lg:grid-cols-[1fr_auto] lg:items-end">
            <div>
              <div className="text-xs font-medium text-ink-3">Progress</div>
              <div className="mt-1 flex items-baseline gap-3">
                <span className="text-5xl font-semibold tracking-tight">{pct}%</span>
                <span className="text-sm text-ink-3 tabular-nums">
                  {completed} of {total} captures
                </span>
              </div>
            </div>
            {eta != null && (
              <div className="text-sm text-ink-3 lg:text-right">
                About <span className="font-medium text-ink">{formatDuration(eta)}</span> left
              </div>
            )}
          </div>
          <div className="mt-4">
            <ProgressBar value={completed} max={total} tone={run.status === "completed" ? "good" : "accent"} />
          </div>

          <ol className="mt-6 grid grid-cols-4 gap-3">
            {PHASES.map((name, i) => {
              const state = i < phase ? "done" : i === phase ? "current" : "todo";
              return (
                <li key={name} className="flex items-center gap-2.5">
                  <span
                    className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ring-1 ring-inset ${
                      state === "todo"
                        ? "bg-surface-2 text-ink-3 ring-[var(--hairline)]"
                        : state === "current" && active
                          ? "bg-accent-strong text-white ring-accent-strong"
                          : "bg-accent-wash text-accent ring-accent/30"
                    }`}
                  >
                    {state === "done" || (!active && i === phase) ? (
                      <Check className="h-4 w-4" strokeWidth={2.5} />
                    ) : (
                      <span className="text-xs font-semibold">{i + 1}</span>
                    )}
                  </span>
                  <span className={`hidden text-sm sm:block ${state === "todo" ? "text-ink-3" : "font-medium"}`}>
                    {name}
                  </span>
                </li>
              );
            })}
          </ol>

          {active && run.status !== "queued" && (workers.length <= 1 || phase !== 1) && (
            <div className="mt-6 flex items-center gap-3 rounded-xl bg-surface-2 px-4 py-3 text-sm">
              <Spinner className="h-4 w-4 text-accent" />
              <div className="min-w-0">
                {run.current && <PromptLabel current={run.current} run={run} />}
                <span className="text-ink-2">
                  {run.status === "cancelling" ? "Cancelling…" : (run.step ?? "Starting…")}
                </span>
              </div>
            </div>
          )}
        </Card>

        <div className="col-span-4 grid grid-cols-2 grid-rows-2 gap-4">
          <StatTile label="Elapsed" value={formatDuration(end - started)} />
          <StatTile
            label="PCAPs"
            value={run.outputs.pcaps.toLocaleString()}
            hint={formatBytes(run.outputs.pcap_bytes)}
          />
          <StatTile
            label="Hardware"
            // Many GPUs don't fit a tile; the full list is in the header and on each worker
            value={(run.assigned_gpus?.length ?? 0) > 2 ? `${run.assigned_gpus!.length} GPUs` : hardwareLabel(run)}
            hint={
              run.gpu_memory_mb
                ? `~${(run.gpu_memory_mb / 1024).toFixed(1)} GB ${workers.length > 1 ? "per worker" : "reserved"}${run.models.length > 1 ? ", for the largest model" : ""}`
                : undefined
            }
          />
          <StatTile label="Max tokens" value={run.config.max_tokens.toLocaleString()} />
        </div>

        {variable && run.variants.length > 0 && (
          <Card
            className="col-span-12"
            title={`Progress by ${variable.one}`}
            description={`Every prompt is captured once per ${variable.one}. They take turns, so each ${variable.one} advances at the same pace.`}
          >
            <div className="grid grid-cols-4 gap-3">
              {run.variants.map((v, i) => {
                const done = v.done ?? 0;
                const total = v.total ?? 0;
                return (
                  <div key={v.key} className="min-w-0 rounded-xl border border-hairline px-4 py-3">
                    <div className="flex items-center justify-between gap-2 text-sm">
                      <span className="flex min-w-0 items-center gap-2 font-medium">
                        <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: variantColor(i) }} />
                        <span className="truncate" title={v.label}>
                          {variantLabel(run.experiment, v)}
                        </span>
                      </span>
                      <span className="shrink-0 text-xs text-ink-3 tabular-nums">
                        {done} / {total}
                      </span>
                    </div>
                    <div className="mt-2">
                      <ProgressBar value={done} max={total} tone={total > 0 && done >= total ? "good" : "accent"} />
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>
        )}

        {workers.length > 1 && (
          <Card
            className="col-span-12"
            title="Workers"
            description="Each worker runs its own copy of the model, with its own network and capture, on its share of the prompts."
          >
            {/* Two columns on wide screens: with workers dealt out over 2 GPUs in turn, each column is one GPU */}
            <div className="grid gap-3 2xl:grid-cols-2">
              {workers.map((w, k) => (
                <WorkerRow key={k} index={k} worker={w} run={run} active={active} />
              ))}
            </div>
          </Card>
        )}
      </div>

      {run.cleanup && (
        <Card
          title="Docker cleanup"
          description="Everything this run created was removed when it ended. Nothing else on the host was touched."
        >
          <dl className="grid gap-4 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-xs text-ink-3">Containers</dt>
              <dd className="mt-0.5">
                {run.cleanup.containers.length > 0 ? run.cleanup.containers.join(", ") : "None left to remove"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-ink-3">Networks</dt>
              <dd className="mt-0.5 break-all">
                {(run.cleanup.networks ?? (run.cleanup.network ? [run.cleanup.network] : [])).join(", ") || "None"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-ink-3">Images</dt>
              <dd className="mt-0.5 break-all">
                {run.cleanup.images.length > 0 ? run.cleanup.images.join(", ") : "None"}
              </dd>
            </div>
          </dl>
          {run.cleanup.errors.length > 0 && (
            <ul className="mt-4 list-disc space-y-1 pl-5 text-sm text-critical-text">
              {run.cleanup.errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          )}
        </Card>
      )}

      <div className="overflow-hidden rounded-2xl border border-hairline bg-[#0f0f0e] shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
        <div className="flex items-center justify-between border-b border-white/10 px-4 py-2.5">
          <div className="text-xs font-medium text-zinc-300">Live log</div>
          {active && (
            <span className="flex items-center gap-1.5 text-[11px] text-zinc-400">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-zinc-300" /> following
            </span>
          )}
        </div>
        <div
          ref={logBox}
          onScroll={(e) => {
            const box = e.currentTarget;
            follow.current = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
          }}
          className="h-96 overflow-auto px-4 py-3 font-mono text-xs leading-5 text-zinc-300"
        >
          {lines.length === 0 ? (
            <span className="text-zinc-500">Waiting for output…</span>
          ) : (
            lines.map((line, i) => (
              <div key={i} className="whitespace-pre-wrap break-words">
                <span className="text-zinc-500">{line.slice(0, 8)}</span>
                <span className={/ERROR|⚠/.test(line) ? "text-[#e66767]" : /✓/.test(line) ? "text-zinc-100" : ""}>
                  {line.slice(8)}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

function PromptLabel({ current, run }: { current: CurrentCapture; run: Run }) {
  // On experiments that compare variants, also which one (temperature, model, network condition)
  const variant = EXPERIMENTS.find((e) => e.slug === run.experiment)?.variable
    ? run.variants.find((v) => v.key === current.variant)
    : undefined;
  return (
    <span className="font-medium">
      Prompt #{String(current.prompt).padStart(2, "0")}
      {current.iteration != null && ` · iteration ${current.iteration}/${run.config.repeat}`}
      {variant && ` · ${variantLabel(run.experiment, variant)}`}
      <span className="text-ink-3"> · </span>
    </span>
  );
}

function WorkerRow({
  index,
  worker,
  run,
  active,
}: {
  index: number;
  worker: RunWorker;
  run: Run;
  active: boolean;
}) {
  const done = worker.done ?? 0;
  const total = worker.total;
  const finished = total != null && done >= total;
  return (
    <div className="flex items-center gap-3 rounded-xl border border-hairline px-4 py-2.5 text-sm">
      <span className="w-20 shrink-0 text-xs font-medium text-ink-3">
        Worker {index + 1}
        <span className="block font-normal">{worker.gpus.length ? `GPU ${worker.gpus.join(", ")}` : "CPU"}</span>
      </span>
      <div className="flex min-w-0 flex-1 items-center gap-3">
        {worker.current ? (
          <>
            <Spinner className="h-3.5 w-3.5 shrink-0 text-accent" />
            <div className="min-w-0 truncate" title={worker.step ?? undefined}>
              <PromptLabel current={worker.current} run={run} />
              <span className="text-ink-2">{worker.step ?? "Starting…"}</span>
            </div>
          </>
        ) : (
          <span className="truncate text-ink-3">
            {finished ? "Finished its prompts" : active ? "Waiting for setup" : "Stopped"}
          </span>
        )}
      </div>
      {total != null && (
        <div className="w-24 shrink-0">
          <div className="mb-1 text-right text-xs text-ink-3 tabular-nums">
            {done} / {total}
          </div>
          <ProgressBar value={done} max={total} tone={finished ? "good" : "accent"} />
        </div>
      )}
    </div>
  );
}
