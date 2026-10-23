"use client";

import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";

import { api, type AgentTask, type TaskCatalog } from "@/lib/api";
import { Segmented, buttonClass } from "@/components/ui";
import { useConfirm } from "@/components/ConfirmDialog";
import { Section } from "./FormSection";

type Category = TaskCatalog["categories"][number];

export const sameTasks = (a: AgentTask[], b: AgentTask[]) =>
  a.length === b.length && a.every((t, i) => t.text === b[i].text && (t.state ?? null) === (b[i].state ?? null));

/**
 * The tasks of an agentic experiment with tasks of its own (Agent to Infrastructure, PLC, Endpoint), one
 * category at a time: edit, remove or add to them, as in Custom Prompts. Every edit goes straight into
 * the form's catalog, so the task counts follow, and is saved shortly after (PUT /api/<slug>/tasks/<category>).
 * `onPending` is true from an edit until it is saved: a run reads the saved tasks.
 */
export function TasksEditor({
  experiment,
  catalog,
  onChange,
  onPending,
}: {
  experiment: string;
  catalog: TaskCatalog;
  onChange: (catalog: TaskCatalog) => void;
  onPending: (pending: boolean) => void;
}) {
  const [slug, setSlug] = useState(catalog.categories[0].slug);
  const [revision, setRevision] = useState(0);
  const [save, setSave] = useState<"idle" | "saving" | "saved" | "failed">("idle");
  const dirty = useRef(new Set<string>()); // categories edited since their last save
  const [confirm, dialog] = useConfirm();
  const limits = catalog.editable!;
  const states = catalog.states ?? [];
  const category = catalog.categories.find((c) => c.slug === slug)!;
  const texts = category.texts ?? [];

  useEffect(() => {
    if (revision === 0) return;
    const timer = setTimeout(() => {
      const pending = [...dirty.current];
      dirty.current.clear();
      Promise.all(
        pending.map((s) =>
          api(`/${experiment}/tasks/${s}`, {
            method: "PUT",
            body: JSON.stringify({ tasks: catalog.categories.find((c) => c.slug === s)!.texts }),
          }),
        ),
      )
        .then(() => {
          setSave("saved");
          if (dirty.current.size === 0) onPending(false); // nothing edited while saving
        })
        .catch(() => {
          pending.forEach((s) => dirty.current.add(s)); // saved with the next edit
          setSave("failed");
        });
    }, 700);
    return () => clearTimeout(timer);
  }, [experiment, revision, catalog, onPending]);

  function update(next: AgentTask[]) {
    const edited: Category = { ...category, texts: next, tasks: next.map((_, i) => i + 1) };
    onChange({ ...catalog, categories: catalog.categories.map((c) => (c.slug === slug ? edited : c)) });
    dirty.current.add(slug);
    onPending(true);
    setSave("saving");
    setRevision((r) => r + 1);
  }

  async function restore() {
    const builtin = category.builtin ?? [];
    const ok = await confirm({
      title: `Restore the built-in ${category.label} tasks?`,
      body: `The ${texts.length} ${category.label} task${texts.length === 1 ? "" : "s"} here are replaced by the ${builtin.length} built-in ones. Past runs keep the tasks they ran.`,
      confirmLabel: "Restore",
      danger: true,
    });
    if (ok) update(builtin.map((t) => ({ ...t })));
  }

  const isBuiltin = sameTasks(texts, category.builtin ?? []);
  const full = texts.length >= limits.max_tasks;

  return (
    <Section
      title="Edit tasks"
      description="What the agents are asked to do in each category. Edit a task, remove it or add your own; changes are saved for the next runs of this experiment."
      action={
        <div className="flex gap-1">
          <button type="button" onClick={restore} disabled={isBuiltin} className={buttonClass("ghost", "sm")}>
            Restore built-in tasks
          </button>
          <button
            type="button"
            onClick={() => update([...texts, states.length ? { text: "", state: states[0] } : { text: "" }])}
            disabled={full}
            className={buttonClass("secondary", "sm")}
          >
            Add task
          </button>
        </div>
      }
    >
      <div className="mb-4 overflow-x-auto [&_button]:whitespace-nowrap">
        <Segmented value={slug} onChange={setSlug} options={catalog.categories.map((c) => ({ value: c.slug, label: c.label }))} />
      </div>
      {texts.length === 0 && (
        <p className="rounded-xl border border-dashed border-hairline px-4 py-6 text-center text-sm text-ink-3">
          No {category.label} tasks. Add one, or restore the built-in tasks.
        </p>
      )}
      <ol className="space-y-2.5">
        {texts.map((task, i) => {
          const empty = !task.text.trim();
          return (
            <li key={i} className="flex items-start gap-3">
              <span className="mt-2 w-7 shrink-0 text-right text-xs font-medium text-ink-3 tabular-nums">{i + 1}</span>
              <div className="min-w-0 flex-1">
                <textarea
                  value={task.text}
                  maxLength={limits.max_chars}
                  rows={Math.min(8, Math.max(2, Math.ceil(task.text.length / 60)))}
                  onChange={(e) => update(texts.map((t, j) => (j === i ? { ...t, text: e.target.value } : t)))}
                  placeholder="Write what the agents should do"
                  aria-label={`${category.label} task ${i + 1}`}
                  className={`block w-full resize-y rounded-lg border bg-surface px-3 py-2 text-sm leading-5 outline-none transition-shadow placeholder:text-ink-3 focus:border-accent focus:ring-4 focus:ring-accent/15 ${
                    empty ? "border-critical" : "border-hairline"
                  }`}
                />
                {empty && <p className="mt-1 text-xs text-critical-text">Write this task or remove it.</p>}
              </div>
              {states.length > 0 && (
                <select
                  value={task.state ?? states[0]}
                  onChange={(e) => update(texts.map((t, j) => (j === i ? { ...t, state: e.target.value } : t)))}
                  aria-label={`State the plant starts in for ${category.label} task ${i + 1}`}
                  title="State the plant starts in"
                  className="mt-0.5 h-9 w-32 shrink-0 rounded-lg border border-hairline bg-surface px-2 text-sm capitalize outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
                >
                  {states.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              )}
              <button
                type="button"
                onClick={() => update(texts.filter((_, j) => j !== i))}
                className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-ink-3 hover:bg-surface-2 hover:text-critical-text"
                aria-label={`Remove ${category.label} task ${i + 1}`}
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
        {save === "failed" && <span className="text-critical-text">Could not save these tasks. Edit one to try again. </span>}
        {save !== "saving" &&
          (isBuiltin
            ? `These are the ${texts.length} built-in ${category.label} tasks, unchanged.`
            : `Up to ${limits.max_tasks} tasks in a category. Each run keeps a copy of the tasks it ran.`)}
        {states.length > 0 && " The state is how the brewery starts the task: normal, with faults, or in a changeover."}
      </p>
      {dialog}
    </Section>
  );
}
