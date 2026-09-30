"use client";

import { useEffect, useState } from "react";

import { api, type Settings } from "@/lib/api";
import { Alert, Card, Field, Spinner, buttonClass, inputClass } from "@/components/ui";

export function StorageCard() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api<Settings>("/settings")
      .then((s) => {
        setSettings(s);
        setPath(s.results_dir);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  async function save(method: "PUT" | "DELETE") {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const s = await api<Settings>("/settings/results-dir", {
        method,
        body: method === "PUT" ? JSON.stringify({ path }) : undefined,
      });
      setSettings(s);
      setPath(s.results_dir);
      setSaved(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const isDefault = settings && settings.results_dir === settings.results_default;
  const others = settings?.results_dirs.filter((d) => d !== settings.results_dir) ?? [];

  return (
    <Card
      title="Storage"
      description="Where new runs save their PCAPs, logs and results: a folder on the machine running the API."
    >
      <div className="space-y-4">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            save("PUT");
          }}
          className="flex flex-col gap-3 sm:flex-row sm:items-end"
        >
          <div className="flex-1">
            <Field label="Results folder" hint="An absolute path. It is created if it doesn't exist.">
              <input
                value={path}
                onChange={(e) => {
                  setPath(e.target.value);
                  setSaved(false);
                }}
                placeholder="/data/mallm-results"
                className={`${inputClass} font-mono text-xs`}
              />
            </Field>
          </div>
          <div className="flex gap-2 sm:mb-[22px]">
            <button type="submit" disabled={busy || !path.trim() || path === settings?.results_dir} className={buttonClass()}>
              {busy && <Spinner />} Save
            </button>
            {settings && !isDefault && (
              <button type="button" onClick={() => save("DELETE")} disabled={busy} className={buttonClass("secondary")}>
                Use default
              </button>
            )}
          </div>
        </form>

        {error && <Alert>{error}</Alert>}
        {saved && !error && <p className="text-xs text-good-text">Saved. New runs are stored in this folder.</p>}

        {others.length > 0 && (
          <div className="rounded-xl bg-surface-2 px-4 py-3">
            <div className="text-xs font-medium text-ink-2">Earlier runs stay where they were saved and are still listed:</div>
            <ul className="mt-1.5 space-y-1">
              {others.map((d) => (
                <li key={d} className="text-xs text-ink-3">
                  <code className="block truncate">{d}</code>
                </li>
              ))}
            </ul>
          </div>
        )}
        <p className="text-xs text-ink-3">
          To move runs somewhere else, use <span className="font-medium text-ink-2">Export files</span> on a run.
          On macOS, Docker Desktop can only mount shared folders (Settings → Resources → File sharing); /Users and /Volumes
          are shared by default.
        </p>
      </div>
    </Card>
  );
}
