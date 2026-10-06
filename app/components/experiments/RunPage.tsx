"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Pencil } from "lucide-react";

import { ApiError, api, isActive, type Run } from "@/lib/api";
import { experimentHref, experimentName } from "@/lib/experiments";
import { useInterval } from "@/lib/useInterval";
import { Alert, Loading, StatusPill, buttonClass } from "@/components/ui";
import { useConfirm } from "@/components/ConfirmDialog";
import { formatBytes, hardwareLabel } from "@/lib/format";
import { RunMonitor } from "./RunMonitor";
import { RunResults } from "./RunResults";
import { RunBadge, comparesText, runTemperature, runTitle } from "./RunBadge";

type Tab = "monitor" | "results";

export function RunPage({ experiment, id, initialTab }: { experiment: string; id: string; initialTab?: Tab }) {
  const router = useRouter();
  const [confirm, dialog] = useConfirm();
  const [run, setRun] = useState<Run | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [tab, setTab] = useState<Tab | null>(initialTab ?? null);
  const [now, setNow] = useState(() => Date.now());
  const [cancelError, setCancelError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api<Run>(`/${experiment}/runs/${id}`)
      .then((r) => {
        setRun(r);
        setNow(Date.now());
      })
      .catch((e) => e instanceof ApiError && e.status === 404 && setNotFound(true));
  }, [experiment, id]);

  const active = run ? isActive(run) : !notFound;
  useEffect(refresh, [refresh]);
  useInterval(refresh, active ? 2000 : null);
  useInterval(() => setNow(Date.now()), active ? 1000 : null);

  function selectTab(next: Tab) {
    setTab(next);
    window.history.replaceState(null, "", `?tab=${next}`);
  }

  async function cancel() {
    const ok = await confirm({
      title: "Cancel this run?",
      body: "The current capture stops. Captures already finished are kept, and the run's Docker containers, network and images are removed.",
      confirmLabel: "Cancel run",
      danger: true,
    });
    if (!ok) return;
    setCancelError(null);
    try {
      setRun(await api<Run>(`/${experiment}/runs/${id}/cancel`, { method: "POST" }));
    } catch (e) {
      setCancelError((e as Error).message);
    }
  }

  async function remove() {
    if (!run) return;
    const ok = await confirm({
      title: `Delete experiment #${run.number ?? ""}?`,
      body: `Its ${run.outputs.pcaps} PCAPs (${formatBytes(run.outputs.pcap_bytes)}), logs and results are permanently deleted.`,
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    setCancelError(null);
    try {
      await api(`/${experiment}/runs/${id}`, { method: "DELETE" });
      router.push(experimentHref(experiment));
    } catch (e) {
      setCancelError((e as Error).message);
    }
  }

  if (notFound) {
    return (
      <Alert tone="warning">
        Run <code>{id}</code> was not found.{" "}
        <Link href={experimentHref(experiment)} className="font-medium text-ink underline">
          Back to runs
        </Link>
      </Alert>
    );
  }
  if (!run) return <Loading label="Loading run…" />;

  // Finished runs open on their results; live runs on the monitor.
  const current: Tab = tab ?? (active || run.outputs.pcaps === 0 ? "monitor" : "results");
  const prompts = run.prompt_count ?? run.config.prompts?.length ?? 60;
  const compares = comparesText(run);
  const temperature = runTemperature(run);
  const meta = [
    ...(compares ? [compares] : []),
    hardwareLabel(run),
    ...(temperature != null ? [`temperature ${temperature}`] : []),
    `${prompts} prompt${prompts === 1 ? "" : "s"}`,
    ...(run.config.repeat ? [`× ${run.config.repeat}`] : []),
    ...((run.config.workers ?? 1) > 1 ? [`${run.config.workers} workers`] : []),
  ];

  return (
    <div>
      <nav className="mb-4 flex items-center gap-1.5 text-xs text-ink-3">
        <Link href={experimentHref(experiment)} className="hover:text-ink">
          {experimentName(experiment)}
        </Link>
        <span>/</span>
        <span className="flex items-center gap-1.5 text-ink-2">
          <RunBadge number={run.number} /> {run.id}
        </span>
      </nav>

      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-4">
          <RunBadge number={run.number} size="lg" />
          <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <RunName run={run} onRenamed={setRun} />
            <StatusPill status={run.status} />
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-3">
            <span className="text-ink-2">{run.models.join(", ")}</span>
            {meta.map((text) => (
              <span key={text}>{text}</span>
            ))}
            <span>{new Date(run.created_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}</span>
          </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {run.outputs.pcaps > 0 && (
            <>
              <a href={`/api/${experiment}/runs/${run.id}/export.zip`} className={buttonClass("secondary")} title="PCAPs, client results, logs and run.json">
                Export files
              </a>
              <a href={`/api/${experiment}/runs/${run.id}/captures.csv`} className={buttonClass("secondary")} title="One row per capture with its settings and metrics">
                Metrics CSV
              </a>
            </>
          )}
          {run.status === "running" || run.status === "pending" || run.status === "queued" ? (
            <button type="button" onClick={cancel} className={buttonClass("danger")}>
              Cancel run
            </button>
          ) : (
            !active && (
              <button type="button" onClick={remove} className={`${buttonClass("secondary")} hover:text-critical-text`}>
                Delete
              </button>
            )
          )}
        </div>
      </div>

      {cancelError && <div className="mb-4"><Alert>{cancelError}</Alert></div>}
      {run.error && <div className="mb-4"><Alert>{run.error}</Alert></div>}

      <div className="mb-6 flex gap-1 border-b border-hairline">
        {(
          [
            { id: "monitor", label: "Monitor", badge: null },
            { id: "results", label: "Results", badge: run.outputs.pcaps || null },
          ] as const
        ).map(({ id: t, label, badge }) => (
          <button
            key={t}
            type="button"
            onClick={() => selectTab(t)}
            className={`-mb-px inline-flex items-center gap-2 border-b-2 px-3 pb-2.5 text-sm transition-colors ${
              current === t ? "border-accent font-medium text-ink" : "border-transparent text-ink-3 hover:text-ink"
            }`}
          >
            {label}
            {badge != null && (
              <span className="rounded-full bg-surface-2 px-1.5 text-[11px] font-medium text-ink-2 tabular-nums">{badge}</span>
            )}
          </button>
        ))}
      </div>

      {current === "monitor" ? <RunMonitor run={run} now={now} /> : <RunResults run={run} live={active} />}
      {dialog}
    </div>
  );
}

/** The run's title; click the pencil to name or rename it. */
function RunName({ run, onRenamed }: { run: Run; onRenamed: (run: Run) => void }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      onRenamed(await api<Run>(`/${run.experiment}/runs/${run.id}`, { method: "PATCH", body: JSON.stringify({ name: value }) }));
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <h1 className="group flex min-w-0 items-center gap-2 text-2xl font-semibold tracking-tight">
        <span className="truncate">{runTitle(run)}</span>
        <button
          type="button"
          onClick={() => {
            setValue(run.name ?? "");
            setEditing(true);
          }}
          className="rounded-lg p-1 text-ink-3 hover:bg-surface-2 hover:text-ink"
          aria-label="Rename"
          title="Rename"
        >
          <Pencil className="h-4 w-4" />
        </button>
      </h1>
    );
  }
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        save();
      }}
      className="flex items-center gap-2"
    >
      <input
        autoFocus
        value={value}
        maxLength={60}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => e.key === "Escape" && setEditing(false)}
        placeholder={runTitle({ ...run, name: null })}
        className="h-9 w-72 rounded-lg border border-accent bg-surface px-3 text-lg font-semibold outline-none ring-4 ring-accent/15"
      />
      <button type="submit" disabled={saving} className={buttonClass("primary", "sm")}>
        Save
      </button>
      <button type="button" onClick={() => setEditing(false)} className={buttonClass("ghost", "sm")}>
        Cancel
      </button>
    </form>
  );
}
