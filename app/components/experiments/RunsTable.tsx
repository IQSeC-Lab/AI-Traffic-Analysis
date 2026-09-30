"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Trash2 } from "lucide-react";

import { api, isActive, type Run } from "@/lib/api";
import { experimentHref, runHref } from "@/lib/experiments";
import { formatBytes, formatDuration, hardwareLabel, timeAgo } from "@/lib/format";
import { useInterval } from "@/lib/useInterval";
import { Alert, ButtonLink, EmptyState, Loading, ProgressBar, StatusPill } from "@/components/ui";
import { useConfirm } from "@/components/ConfirmDialog";
import { RunBadge, comparesText, modelName, runTitle } from "./RunBadge";

export function RunsTable({ experiment }: { experiment: string }) {
  const router = useRouter();
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [error, setError] = useState<string | null>(null);
  const [confirm, dialog] = useConfirm();

  const refresh = useCallback(() => {
    api<Run[]>(`/${experiment}/runs`)
      .then((r) => {
        setRuns(r);
        setNow(Date.now());
      })
      .catch(() => setRuns([]));
  }, [experiment]);
  useEffect(refresh, [refresh]);
  useInterval(refresh, runs?.some(isActive) ? 3000 : null);

  async function remove(run: Run) {
    const ok = await confirm({
      title: `Delete experiment #${run.number ?? ""}?`,
      body: (
        <>
          <span className="font-medium text-ink">{runTitle(run)}</span> · {run.id}. Its{" "}
          {run.outputs.pcaps} PCAPs ({formatBytes(run.outputs.pcap_bytes)}), logs and results are permanently deleted.
        </>
      ),
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    setError(null);
    try {
      await api(`/${experiment}/runs/${run.id}`, { method: "DELETE" });
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (!runs) return <Loading />;
  if (runs.length === 0) {
    return (
      <EmptyState
        title="No runs yet"
        action={
          <ButtonLink href={`${experimentHref(experiment)}/new`}>
            Start your first run
          </ButtonLink>
        }
      >
        Each run streams prompts through a fresh model container and captures every packet for analysis.
      </EmptyState>
    );
  }

  return (
    <>
    {error && <div className="mb-4"><Alert>{error}</Alert></div>}
    <div className="overflow-hidden rounded-2xl border border-hairline bg-surface shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-hairline bg-surface-2/60 text-xs text-ink-3">
            <tr>
              <th className="px-5 py-2.5 font-medium">Experiment</th>
              <th className="px-3 py-2.5 font-medium">Status</th>
              <th className="px-3 py-2.5 font-medium">Progress</th>
              <th className="px-3 py-2.5 font-medium">Captured</th>
              <th className="px-3 py-2.5 font-medium">Hardware</th>
              <th className="px-3 py-2.5 font-medium">Started</th>
              <th className="w-20" />
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--hairline)]">
            {runs.map((run) => {
              const end = run.finished_at ? new Date(run.finished_at).getTime() : now;
              const compares = comparesText(run);
              return (
                <tr
                  key={run.id}
                  onClick={() => router.push(runHref(run))}
                  className="group cursor-pointer transition-colors hover:bg-surface-2/60"
                >
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-3">
                      <RunBadge number={run.number} />
                      <div className="min-w-0">
                        <div className="truncate font-medium">{runTitle(run)}</div>
                        <div className="truncate text-xs text-ink-3">
                          {[run.name ? run.models.map(modelName).join(", ") : run.id, compares].filter(Boolean).join(" · ")}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-3">
                    <StatusPill status={run.status} />
                  </td>
                  <td className="w-44 px-3 py-3">
                    {run.status === "queued" ? (
                      <span className="text-xs text-ink-3" title={run.queue?.reason ?? undefined}>
                        #{run.queue?.position ?? "–"} in queue
                      </span>
                    ) : (
                      <div className="flex items-center gap-2 text-xs text-ink-3 tabular-nums">
                        <ProgressBar value={run.progress.completed} max={run.progress.total} />
                        <span className="shrink-0">
                          {run.progress.completed}/{run.progress.total}
                        </span>
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-3 text-xs text-ink-2 tabular-nums">
                    {run.outputs.pcaps} PCAPs · {formatBytes(run.outputs.pcap_bytes)}
                  </td>
                  <td className="px-3 py-3 text-xs text-ink-2">
                    {hardwareLabel(run)}
                  </td>
                  <td className="px-3 py-3 text-xs text-ink-2">
                    <div>{timeAgo(run.created_at, now)}</div>
                    <div className="text-ink-3">{formatDuration(end - new Date(run.created_at).getTime())}</div>
                  </td>
                  <td className="pr-4">
                    <div className="flex items-center justify-end gap-1">
                      {!isActive(run) && (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            remove(run);
                          }}
                          className="rounded-lg p-1.5 text-ink-3 hover:bg-surface-2 hover:text-critical-text"
                          aria-label={`Delete experiment #${run.number ?? run.id}`}
                          title="Delete"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
    {dialog}
    </>
  );
}
