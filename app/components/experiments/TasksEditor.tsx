"use client";

import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";

import { api, type AgentTask, type TaskCatalog } from "@/lib/api";
import { Alert, Loading, Segmented, buttonClass } from "@/components/ui";
import { useConfirm } from "@/components/ConfirmDialog";
import { Section } from "./FormSection";

const areaClass =
  "block w-full resize-y rounded-lg border bg-surface px-3 py-2 text-sm leading-5 outline-none transition-shadow placeholder:text-ink-3 focus:border-accent focus:ring-4 focus:ring-accent/15";
const rowsFor = (text: string, max: number) => Math.min(max, Math.max(2, Math.ceil(text.length / 60)));

/**
 * The tasks of an agentic experiment, one category at a time: edit, remove or add to them, as in Custom
 * Prompts (api/experiments/task_store.py). A category's tasks are loaded when its tab is opened, every
 * edit updates the form's task counts right away, and the category is saved shortly after. A MARBLE task
 * also has its agents, whose profiles can be edited too; a new task copies the agents of the one above.
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
  const categories = catalog.categories.filter((c) => !c.disabled);
  // Opens on a small category: MARBLE's bargaining, first in Agent to LLM, is 100 tasks and about 1.5 MB
  const [slug, setSlug] = useState((categories.find((c) => c.tasks.length <= catalog.dataset_tasks) ?? categories[0])?.slug ?? "");
  const [lists, setLists] = useState<Record<string, AgentTask[]>>({}); // the categories loaded, as edited here
  const [templates, setTemplates] = useState<Record<string, AgentTask>>({}); // what a new task starts from in an empty one
  const [open, setOpen] = useState<Set<string>>(new Set()); // tasks whose agents are shown, as "<category>:<index>"
  const [revision, setRevision] = useState(0);
  const [save, setSave] = useState<"idle" | "saving" | "saved" | "failed">("idle");
  const [error, setError] = useState<string | null>(null);
  const requested = useRef(new Set<string>());
  const dirty = useRef(new Set<string>()); // categories edited since their last save
  const [confirm, dialog] = useConfirm();
  const limits = catalog.editable!;
  const states = catalog.states ?? [];
  const category = catalog.categories.find((c) => c.slug === slug);
  const texts = lists[slug];

  useEffect(() => {
    if (!slug || requested.current.has(slug)) return;
    requested.current.add(slug);
    api<{ tasks: AgentTask[]; template: AgentTask }>(`/${experiment}/tasks/${slug}`)
      .then((d) => {
        setLists((cur) => ({ ...cur, [slug]: d.tasks }));
        setTemplates((cur) => ({ ...cur, [slug]: d.template }));
      })
      .catch((e: Error) => {
        requested.current.delete(slug);
        setError(e.message);
      });
  }, [experiment, slug]);

  useEffect(() => {
    if (revision === 0) return;
    const timer = setTimeout(() => {
      const pending = [...dirty.current];
      dirty.current.clear();
      Promise.all(pending.map((s) => api(`/${experiment}/tasks/${s}`, { method: "PUT", body: JSON.stringify({ tasks: lists[s] }) })))
        .then(() => {
          setSave("saved");
          if (dirty.current.size === 0) onPending(false); // nothing edited while saving
        })
        .catch((e: Error) => {
          pending.forEach((s) => dirty.current.add(s)); // saved with the next edit
          setError(e.message);
          setSave("failed");
        });
    }, 700);
    return () => clearTimeout(timer);
  }, [experiment, revision, lists, onPending]);

  if (!category) return null;

  function counts(next: AgentTask[], edited: boolean): TaskCatalog {
    const changed = { ...category!, tasks: next.map((_, i) => i + 1), edited };
    return { ...catalog, categories: catalog.categories.map((c) => (c.slug === slug ? changed : c)) };
  }

  function update(next: AgentTask[]) {
    setLists((cur) => ({ ...cur, [slug]: next }));
    onChange(counts(next, true));
    dirty.current.add(slug);
    onPending(true);
    setError(null);
    setSave("saving");
    setRevision((r) => r + 1);
  }

  async function restore() {
    const ok = await confirm({
      title: `Restore the built-in ${category!.label} tasks?`,
      body: `Your edits to the ${category!.label} tasks are discarded and the built-in ones come back.${limits.shared ? ` ${limits.shared}` : ""} Past runs keep the tasks they ran.`,
      confirmLabel: "Restore",
      danger: true,
    });
    if (!ok) return;
    dirty.current.delete(slug);
    try {
      const d = await api<{ tasks: AgentTask[] }>(`/${experiment}/tasks/${slug}`, { method: "DELETE" });
      setLists((cur) => ({ ...cur, [slug]: d.tasks }));
      onChange(counts(d.tasks, false));
      setSave("saved");
      if (dirty.current.size === 0) onPending(false);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  function add() {
    const last = texts!.at(-1);
    const from = last ?? templates[slug];
    update([...texts!, { ...from, text: "", agents: from.agents?.map((a) => ({ ...a })) }]);
  }

  const toggle = (key: string, isOpen: boolean) =>
    setOpen((cur) => {
      const next = new Set(cur);
      if (isOpen) next.add(key);
      else next.delete(key);
      return next;
    });

  const hasAgents = texts?.some((t) => t.agents) ?? false;

  return (
    <Section
      title="Edit tasks"
      description={`What the agents are asked to do in each category. Edit a task, remove it or add your own; changes are saved for the next runs.${limits.shared ? ` ${limits.shared}` : ""}`}
      action={
        <div className="flex gap-1">
          <button type="button" onClick={restore} disabled={!category.edited} className={buttonClass("ghost", "sm")}>
            Restore built-in tasks
          </button>
          <button type="button" onClick={add} disabled={!texts || texts.length >= limits.max_tasks} className={buttonClass("secondary", "sm")}>
            Add task
          </button>
        </div>
      }
    >
      <div className="mb-4 overflow-x-auto [&_button]:whitespace-nowrap">
        <Segmented value={slug} onChange={setSlug} options={categories.map((c) => ({ value: c.slug, label: c.label }))} />
      </div>
      {error && <Alert>{error}</Alert>}
      {!texts && !error && <Loading label="Loading tasks…" />}
      {texts && (
        <>
          {texts.length === 0 && (
            <p className="rounded-xl border border-dashed border-hairline px-4 py-6 text-center text-sm text-ink-3">
              No {category.label} tasks. Add one, or restore the built-in tasks.
            </p>
          )}
          {/* Scrolls on its own, so that a category of 100 tasks doesn't push the rest of the form away; the padding keeps focus rings in view */}
          <ol className="-m-1 max-h-[44rem] space-y-2.5 overflow-y-auto p-1">
            {texts.map((task, i) => {
              const empty = !task.text.trim();
              const key = `${slug}:${i}`;
              const set = (patch: Partial<AgentTask>) => update(texts.map((t, j) => (j === i ? { ...t, ...patch } : t)));
              return (
                <li key={key} className="flex items-start gap-3">
                  <span className="mt-2 w-7 shrink-0 text-right text-xs font-medium text-ink-3 tabular-nums">{i + 1}</span>
                  <div className="min-w-0 flex-1">
                    <textarea
                      value={task.text}
                      maxLength={limits.max_chars}
                      rows={rowsFor(task.text, 8)}
                      onChange={(e) => set({ text: e.target.value })}
                      placeholder="Write what the agents should do"
                      aria-label={`${category.label} task ${i + 1}`}
                      className={`${areaClass} ${empty ? "border-critical" : "border-hairline"}`}
                    />
                    {empty && <p className="mt-1 text-xs text-critical-text">Write this task or remove it.</p>}
                    {task.agents && (
                      <details className="mt-1.5" open={open.has(key)} onToggle={(e) => toggle(key, e.currentTarget.open)}>
                        <summary className="cursor-pointer select-none text-xs text-ink-3 hover:text-ink">
                          Agents: {task.agents.map((a) => a.id).join(", ")}
                        </summary>
                        {/* Only rendered when open: a category can have 100 tasks of 4 agents */}
                        {open.has(key) && (
                          <div className="mt-2 space-y-2 border-l-2 border-hairline pl-3">
                            {task.agents.map((agent, j) => (
                              <label key={agent.id} className="block">
                                <span className="mb-1 block text-xs font-medium text-ink-2">{agent.id}</span>
                                <textarea
                                  value={agent.profile}
                                  maxLength={limits.max_chars}
                                  rows={rowsFor(agent.profile, 6)}
                                  onChange={(e) => set({ agents: task.agents!.map((a, k) => (k === j ? { ...a, profile: e.target.value } : a)) })}
                                  className={`${areaClass} border-hairline text-xs`}
                                />
                              </label>
                            ))}
                          </div>
                        )}
                      </details>
                    )}
                  </div>
                  {states.length > 0 && (
                    <select
                      value={task.state ?? states[0]}
                      onChange={(e) => set({ state: e.target.value })}
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
              (category.edited
                ? `Up to ${limits.max_tasks} tasks in a category. Each run keeps a copy of the tasks it ran.`
                : `These are the ${texts.length} built-in ${category.label} tasks, unchanged.`)}
            {hasAgents &&
              " Each task's agents and their roles are under Agents: in some categories they hold part of the task, such as the bug's details or the candidate diagnoses. A new task starts with the agents of the task above it."}
            {states.length > 0 && " The state is how the brewery starts the task: normal, with faults, or in a changeover."}
          </p>
        </>
      )}
      {dialog}
    </Section>
  );
}
