"use client";

import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";

import { api, type Prompt } from "@/lib/api";
import { Alert, Field, Spinner, buttonClass, inputClass } from "@/components/ui";

/** Add a prompt (or edit a custom one). Categories are free text: pick one or type a new name. */
export function PromptDialog({
  prompt,
  categories,
  defaultCategory = "",
  onSaved,
  onClose,
}: {
  prompt?: Prompt;
  categories: string[];
  defaultCategory?: string;
  onSaved: (prompt: Prompt) => void;
  onClose: () => void;
}) {
  const [category, setCategory] = useState(prompt?.category ?? defaultCategory);
  const [text, setText] = useState(prompt?.text ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [addedCount, setAddedCount] = useState(0);
  const textRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function save(addAnother: boolean) {
    setBusy(true);
    setError(null);
    try {
      const saved = await api<Prompt>(prompt ? `/prompts/${prompt.number}` : "/prompts", {
        method: prompt ? "PUT" : "POST",
        body: JSON.stringify({ category, text }),
      });
      onSaved(saved);
      if (addAnother) {
        setText("");
        setAddedCount((n) => n + 1);
        textRef.current?.focus();
      } else {
        onClose();
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const valid = category.trim() && text.trim();
  const isNew = !categories.includes(category.trim()) && category.trim() !== "";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save(false);
        }}
        className="relative w-full max-w-xl rounded-2xl border border-hairline bg-surface shadow-2xl"
      >
        <div className="flex items-center justify-between border-b border-hairline px-5 py-4">
          <h2 className="text-base font-semibold">{prompt ? `Edit prompt #${prompt.number}` : "New prompt"}</h2>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-ink-3 hover:bg-surface-2 hover:text-ink" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-4 p-5">
          <Field
            label="Category"
            hint={isNew ? `"${category.trim()}" will be a new category.` : "Pick a category or type a new name."}
          >
            <input
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              maxLength={60}
              placeholder="e.g. Medical"
              className={inputClass}
              autoFocus={!prompt && !defaultCategory}
            />
          </Field>
          {categories.length > 0 && (
            <div className="-mt-2 flex flex-wrap gap-1.5">
              {categories.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setCategory(c)}
                  className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${
                    category.trim() === c
                      ? "border-accent bg-accent-wash font-medium text-ink"
                      : "border-hairline text-ink-3 hover:text-ink"
                  }`}
                >
                  {c}
                </button>
              ))}
            </div>
          )}

          <Field label="Prompt" hint={`${text.trim().length.toLocaleString()} characters. Sent to the model exactly as written.`}>
            <textarea
              ref={textRef}
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={8}
              maxLength={20000}
              placeholder="Write the prompt the model will receive…"
              className={`${inputClass} h-auto resize-y py-2 leading-relaxed`}
              autoFocus={!!prompt || !!defaultCategory}
            />
          </Field>

          {error && <Alert>{error}</Alert>}
          {addedCount > 0 && !error && (
            <p className="text-xs text-good-text">
              {addedCount} prompt{addedCount > 1 ? "s" : ""} added to the library.
            </p>
          )}
        </div>

        <div className="flex flex-wrap justify-end gap-2 border-t border-hairline px-5 py-4">
          <button type="button" onClick={onClose} className={buttonClass("ghost")}>
            {addedCount > 0 ? "Done" : "Cancel"}
          </button>
          {!prompt && (
            <button type="button" onClick={() => save(true)} disabled={busy || !valid} className={buttonClass("secondary")}>
              Save and add another
            </button>
          )}
          <button type="submit" disabled={busy || !valid} className={buttonClass()}>
            {busy && <Spinner />} {prompt ? "Save changes" : "Add prompt"}
          </button>
        </div>
      </form>
    </div>
  );
}
