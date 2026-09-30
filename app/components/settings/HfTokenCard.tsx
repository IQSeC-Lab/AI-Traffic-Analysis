"use client";

import { useEffect, useState } from "react";
import { ExternalLink } from "lucide-react";

import { api, type Settings, type TokenStatus } from "@/lib/api";
import { Alert, Card, Field, Spinner, buttonClass, inputClass } from "@/components/ui";

export function HfTokenCard() {
  const [status, setStatus] = useState<TokenStatus | null>(null);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Settings>("/settings")
      .then((s) => setStatus(s.hf_token))
      .catch((e: Error) => setError(e.message));
  }, []);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setStatus(await api<TokenStatus>("/settings/hf-token", { method: "PUT", body: JSON.stringify({ token }) }));
      setToken("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      setStatus(await api<TokenStatus>("/settings/hf-token", { method: "DELETE" }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      title="Hugging Face"
      description="A token lets you download gated models such as Llama. It is saved on the server and never shown again."
    >
      <div className="space-y-4">
        {status && (
          <div className="flex items-center gap-3 rounded-xl bg-surface-2 px-4 py-3 text-sm">
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ background: status.set ? "var(--good)" : "var(--ink-3)" }}
            />
            <div className="min-w-0 text-ink-2">
              {status.source === "saved" && (
                <>
                  <span className="font-medium text-ink">Token saved</span> <code className="text-ink-3">{status.hint}</code>
                  {status.username && <> · signed in as {status.username}</>}
                </>
              )}
              {status.source === "env" && (
                <>
                  <span className="font-medium text-ink">Using HF_TOKEN</span> from the server environment{" "}
                  <code className="text-ink-3">{status.hint}</code>
                </>
              )}
              {!status.set && "No token set. Only public models can be downloaded."}
            </div>
          </div>
        )}

        <form onSubmit={save} className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="flex-1">
            <Field
              label={status?.source === "saved" ? "Replace token" : "Access token"}
              hint={
                <a
                  href="https://huggingface.co/settings/tokens"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 hover:text-ink"
                >
                  Create a read token on huggingface.co <ExternalLink className="h-3 w-3" />
                </a>
              }
            >
              <input
                type="password"
                autoComplete="off"
                placeholder="hf_…"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                className={inputClass}
              />
            </Field>
          </div>
          <div className="flex gap-2 sm:mb-6">
            <button type="submit" disabled={busy || !token.trim()} className={buttonClass()}>
              {busy && <Spinner />} Save token
            </button>
            {status?.source === "saved" && (
              <button type="button" onClick={remove} disabled={busy} className={buttonClass("secondary")}>
                Remove
              </button>
            )}
          </div>
        </form>

        {error && <Alert>{error}</Alert>}
      </div>
    </Card>
  );
}
