"use client";

import { useCallback, useEffect, useState } from "react";
import { Trash2 } from "lucide-react";

import { ACTIVE_DOWNLOAD_STATUSES, api, type Download, type OllamaModel, type OllamaModelsResponse } from "@/lib/api";
import { formatBytes } from "@/lib/format";
import { useInterval } from "@/lib/useInterval";
import { Alert, Card, Field, ProgressBar, Spinner, StatusPill, buttonClass, inputClass } from "@/components/ui";
import { useConfirm } from "@/components/ConfirmDialog";

/** Models pulled from the Ollama library, for the agentic experiments and the Data Collector on Ollama. */
export function OllamaModels() {
  const [data, setData] = useState<OllamaModelsResponse | null>(null);
  const [model, setModel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirm, confirmDialog] = useConfirm();

  const refresh = useCallback(() => {
    api<OllamaModelsResponse>("/settings/ollama-models")
      .then(setData)
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(refresh, [refresh]);
  const active = data?.downloads.some((d) => ACTIVE_DOWNLOAD_STATUSES.includes(d.status)) ?? false;
  useInterval(refresh, active ? 2000 : null);

  async function download(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api<Download>("/settings/ollama-models/download", { method: "POST", body: JSON.stringify({ model: model.trim() }) });
      setModel("");
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(m: OllamaModel) {
    const ok = await confirm({
      title: `Delete ${m.model}?`,
      body: `Its ${formatBytes(m.size_bytes)} of files are deleted from ${data?.models_dir}. Past runs keep their results; download it again to run it.`,
      confirmLabel: "Delete model",
      danger: true,
    });
    if (!ok) return;
    setError(null);
    try {
      await api(`/settings/ollama-models/${m.model.split("/").map(encodeURIComponent).join("/")}`, { method: "DELETE" });
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const running = data?.downloads.filter((d) => d.status !== "completed") ?? [];

  return (
    <Card
      id="ollama-models"
      title="Ollama models"
      description="Download models from the Ollama library. The agentic experiments use them, and the Data Collector can."
    >
      <div className="space-y-6">
        <form onSubmit={download} className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
          <Field label="Model" hint="Name and tag as on ollama.com/library, e.g. llama3.2:3b">
            <input
              required
              pattern="[A-Za-z0-9][A-Za-z0-9._\-]*(/[A-Za-z0-9._\-]+)?(:[A-Za-z0-9._\-]+)?"
              placeholder="name:tag"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className={inputClass}
            />
          </Field>
          <button type="submit" disabled={busy || !model.trim()} className={`${buttonClass()} sm:mb-[22px]`}>
            {busy && <Spinner />} Download
          </button>
        </form>

        {error && <Alert>{error}</Alert>}

        {running.length > 0 && (
          <div className="space-y-2">
            {running.map((d) => (
              <div key={d.id} className="rounded-xl border border-hairline p-3.5">
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="truncate font-medium">{d.model}</span>
                  <StatusPill status={d.status} />
                </div>
                {d.status === "downloading" && (
                  <div className="mt-2.5 flex items-center gap-3 text-xs text-ink-3 tabular-nums">
                    <ProgressBar value={d.downloaded_bytes ?? 0} max={d.total_bytes ?? 0} />
                    <span className="shrink-0">
                      {formatBytes(d.downloaded_bytes)} / {formatBytes(d.total_bytes)}
                    </span>
                  </div>
                )}
                {d.status === "queued" && <p className="mt-1 text-xs text-ink-3">Waiting for the current download to finish.</p>}
                {d.status === "preparing" && <p className="mt-1 text-xs text-ink-3">Reading the model&apos;s layers…</p>}
                {d.error && <p className="mt-1 text-xs text-critical-text">{d.error}</p>}
              </div>
            ))}
          </div>
        )}

        <div className="overflow-hidden rounded-xl border border-hairline">
          <div className="flex items-center gap-2 border-b border-hairline bg-surface-2/60 px-4 py-2 text-xs text-ink-3">
            <code className="truncate">{data?.models_dir ?? "…"}</code>
          </div>
          {data && data.models.length === 0 && <p className="px-4 py-6 text-center text-sm text-ink-3">No Ollama models yet.</p>}
          <ul className="divide-y divide-[var(--hairline)]">
            {data?.models.map((m) => (
              <li key={m.model} className="flex items-center gap-4 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{m.model}</div>
                  <div className="text-xs text-ink-3">
                    {formatBytes(m.size_bytes)}
                    {m.gpu_memory_mb ? ` · needs ~${(m.gpu_memory_mb / 1024).toFixed(1)} GB of GPU memory` : ""}
                  </div>
                </div>
                {m.downloading ? (
                  <StatusPill status="downloading" />
                ) : m.complete ? (
                  <StatusPill status="completed" />
                ) : (
                  <span className="text-right text-xs text-ink-3">Incomplete · download again to resume</span>
                )}
                {!m.downloading && (
                  <button
                    type="button"
                    onClick={() => remove(m)}
                    className="rounded-lg p-1.5 text-ink-3 hover:bg-surface-2 hover:text-critical-text"
                    aria-label={`Delete ${m.model}`}
                    title="Delete model"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
        <p className="text-xs text-ink-3">
          The agentic experiments need a model that supports tool calls, as llama3.2 does: its page on ollama.com is
          tagged Tools. Without them, tasks where the agents use tools fail.
        </p>
      </div>
      {confirmDialog}
    </Card>
  );
}
