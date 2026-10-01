"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";

import { api, type CustomPrompts } from "@/lib/api";
import { Alert, Loading, buttonClass } from "@/components/ui";
import { useConfirm } from "@/components/ConfirmDialog";
import { Section } from "./FormSection";

const sameList = (a: string[], b: string[]) => a.length === b.length && a.every((text, i) => text === b[i]);

/**
 * The Custom Prompts experiment's own prompts: loaded from and saved to the experiment,
 * never the prompt library. Reports the current list (null while loading) to the form.
 */
export function CustomPromptsEditor({ onChange }: { onChange: (prompts: string[] | null) => void }) {
  const [data, setData] = useState<CustomPrompts | null>(null);
  const [prompts, setPrompts] = useState<string[]>([]);
  const [revision, setRevision] = useState(0); // edits since loading; each one is saved shortly after
  const [save, setSave] = useState<"idle" | "saving" | "saved" | "failed">("idle");
  const [error, setError] = useState<string | null>(null);
  const [confirm, dialog] = useConfirm();

  useEffect(() => {
    api<CustomPrompts>("/custom-prompts/prompts")
      .then((d) => {
        setData(d);
        setPrompts(d.prompts);
        onChange(d.prompts);
      })
      .catch((e: Error) => setError(e.message));
  }, [onChange]);

  useEffect(() => {
    if (revision === 0) return;
    const timer = setTimeout(() => {
      api("/custom-prompts/prompts", { method: "PUT", body: JSON.stringify({ prompts }) })
        .then(() => setSave("saved"))
        .catch(() => setSave("failed"));
    }, 700);
    return () => clearTimeout(timer);
  }, [revision, prompts]);

  function update(next: string[]) {
    setPrompts(next);
    onChange(next);
    setSave("saving");
    setRevision((r) => r + 1);
  }

  async function restoreCrafted() {
    if (!data) return;
    const ok =
      prompts.every((p) => !p.trim()) ||
      (await confirm({
        title: "Replace these prompts with the crafted ones?",
        body: `Your ${prompts.length} prompt${prompts.length === 1 ? "" : "s"} here are replaced by the ${data.crafted.length} crafted prompts of the original experiment. Past runs keep the prompts they used.`,
        confirmLabel: "Replace",
        danger: true,
      }));
    if (ok) update([...data.crafted]);
  }

  const full = data != null && prompts.length >= data.max_prompts;
  const isCrafted = data != null && sameList(prompts, data.crafted);

  return (
    <Section
      title="Prompts"
      description="Written here for this experiment and sent exactly as they appear, spaces and line breaks included. They are saved with the experiment, not in the prompt library."
      action={
        <div className="flex gap-1">
          <button type="button" onClick={restoreCrafted} disabled={!data || isCrafted} className={buttonClass("ghost", "sm")}>
            Use the crafted prompts
          </button>
          <button type="button" onClick={() => update([...prompts, ""])} disabled={!data || full} className={buttonClass("secondary", "sm")}>
            Add prompt
          </button>
        </div>
      }
    >
      {error && <Alert>{error}</Alert>}
      {!data && !error && <Loading label="Loading prompts…" />}
      {data && (
        <>
          {prompts.length === 0 && (
            <p className="rounded-xl border border-dashed border-hairline px-4 py-6 text-center text-sm text-ink-3">
              No prompts. Add one, or use the crafted prompts.
            </p>
          )}
          <ol className="space-y-2.5">
            {prompts.map((text, i) => {
              const empty = !text.trim();
              return (
                <li key={i} className="flex items-start gap-3">
                  <span className="mt-2 w-7 shrink-0 text-right text-xs font-medium text-ink-3 tabular-nums">{i + 1}</span>
                  <div className="min-w-0 flex-1">
                    <textarea
                      value={text}
                      maxLength={data.max_chars}
                      rows={Math.min(14, Math.max(3, text.split("\n").length))}
                      spellCheck={false}
                      onChange={(e) => update(prompts.map((p, j) => (j === i ? e.target.value : p)))}
                      placeholder="Write the prompt"
                      aria-label={`Prompt ${i + 1}`}
                      className={`block w-full resize-y rounded-lg border bg-surface px-3 py-2 font-mono text-xs leading-5 outline-none transition-shadow placeholder:text-ink-3 focus:border-accent focus:ring-4 focus:ring-accent/15 ${
                        empty ? "border-critical" : "border-hairline"
                      }`}
                    />
                    {empty && <p className="mt-1 text-xs text-critical-text">Write this prompt or remove it.</p>}
                  </div>
                  <button
                    type="button"
                    onClick={() => update(prompts.filter((_, j) => j !== i))}
                    className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-ink-3 hover:bg-surface-2 hover:text-critical-text"
                    aria-label={`Remove prompt ${i + 1}`}
                    title="Remove"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </li>
              );
            })}
          </ol>
          <p className="mt-3 text-xs text-ink-3">
            {save === "saving" && "Saving…"}
            {save === "saved" && "Saved. "}
            {save === "failed" && <span className="text-critical-text">Could not save these prompts. They are still used for this run. </span>}
            {save !== "saving" &&
              (isCrafted
                ? `These are the ${data.crafted.length} crafted prompts of 4-Crafted-Prompts, unchanged.`
                : `Up to ${data.max_prompts} prompts. Each run keeps a copy of the prompts it used.`)}
          </p>
        </>
      )}
      {dialog}
    </Section>
  );
}
