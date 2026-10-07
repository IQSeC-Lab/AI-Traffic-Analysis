"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api, type OllamaModel, type OllamaModelsResponse, type Run, type RunConfig, type SystemInfo, type TaskCatalog } from "@/lib/api";
import { runHref } from "@/lib/experiments";
import { formatBytes } from "@/lib/format";
import { Alert, ButtonLink, Field, Loading, Segmented, Spinner, buttonClass, inputClass } from "@/components/ui";
import { Section } from "./FormSection";
import { variantColor } from "./RunBadge";
import { SelectCard } from "./RunForm";

const gb = (mb: number) => `${(mb / 1024).toFixed(1)} GB`;

/** New run of an agentic experiment: MARBLE tasks, each captured once per topology. */
export function AgenticRunForm({ experiment }: { experiment: string }) {
  const router = useRouter();
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [catalog, setCatalog] = useState<TaskCatalog | null>(null);
  const [models, setModels] = useState<OllamaModel[]>([]);
  const [activeRuns, setActiveRuns] = useState<Run[]>([]);

  const [model, setModel] = useState("");
  const [topologies, setTopologies] = useState<string[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [perCategory, setPerCategory] = useState(1);
  const [repeat, setRepeat] = useState(1);
  const [gpuMode, setGpuMode] = useState<"auto" | "manual" | "cpu">("auto");
  const [gpus, setGpus] = useState<number[]>([]);
  const [workers, setWorkers] = useState(1);
  const [name, setName] = useState("");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api<SystemInfo>("/system"),
      api<TaskCatalog>(`/${experiment}/tasks`),
      api<OllamaModelsResponse>("/settings/ollama-models"),
      api<Run[]>("/experiments/active"),
    ])
      .then(([sys, tasks, ollama, active]) => {
        const pulled = ollama.models.filter((m) => m.complete && !m.downloading);
        setSystem(sys);
        setCatalog(tasks);
        setModels(pulled);
        // The model the dataset was collected with, when it is here
        setModel((pulled.find((m) => m.model === tasks.default_model) ?? pulled[0])?.model ?? "");
        setTopologies(tasks.topologies.map((t) => t.key));
        setCategories(tasks.categories.filter((c) => !c.disabled && c.tasks.length > 0).map((c) => c.slug));
        setPerCategory(tasks.dataset_tasks);
        setGpuMode(sys.gpus.length > 0 ? "auto" : "cpu");
        setGpus(sys.gpus.map((g) => g.index));
        setActiveRuns(active);
      })
      .catch((e: Error) => setError(e.message));
  }, [experiment]);

  if (!system || !catalog) {
    return error ? <Alert>{error}</Alert> : <Loading label="Reading the MARBLE tasks…" />;
  }

  const toggle = (list: string[], value: string) => (list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);
  const chosen = catalog.categories.filter((c) => categories.includes(c.slug));
  // Every chosen category runs the same task numbers, so the smallest one sets how many there can be
  const maxTasks = chosen.length ? Math.min(...chosen.map((c) => c.tasks.length)) : catalog.dataset_tasks;
  const taskCount = Math.max(1, Math.min(perCategory, maxTasks));
  const tasks = chosen.length ? chosen[0].tasks.slice(0, taskCount) : [];
  // In the catalog's order, which is the order the run compares them in
  const picked = catalog.topologies.filter((t) => topologies.includes(t.key));
  const total = chosen.length * taskCount * Math.max(1, repeat) * picked.length;

  const onGpu = gpuMode !== "cpu" && system.gpus.length > 0;
  const workerCount = Math.max(1, Math.min(workers, total || 1));
  const needMb = models.find((m) => m.model === model)?.gpu_memory_mb ?? null;
  const hardware = !onGpu ? "CPU" : gpuMode === "auto" ? "Auto GPU" : gpus.length ? `GPU ${gpus.join(", ")}` : "—";
  const canStart =
    catalog.available &&
    system.docker.available &&
    model !== "" &&
    picked.length > 0 &&
    chosen.length > 0 &&
    !starting &&
    !(onGpu && gpuMode === "manual" && gpus.length === 0);

  async function start() {
    setStarting(true);
    setError(null);
    const config: Partial<RunConfig> = {
      model,
      topologies: picked.map((t) => t.key),
      categories: chosen.map((c) => c.slug),
      tasks,
      repeat: repeat > 1 ? repeat : null,
      gpus: !onGpu ? [] : gpuMode === "auto" ? "auto" : gpus,
      workers: workerCount,
      name: name.trim() || null,
    };
    try {
      const run = await api<Run>(`/${experiment}/runs`, { method: "POST", body: JSON.stringify(config) });
      router.push(runHref(run));
    } catch (e) {
      setError((e as Error).message);
      setStarting(false);
    }
  }

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[1fr_20rem]">
      <div className="space-y-6">
        {!catalog.available && (
          <Alert tone="warning">{catalog.problem ?? "The MARBLE code is not on this machine."}</Alert>
        )}

        <Section
          title="Model"
          description="Ollama models downloaded on this machine. Every agent calls the same one."
          action={
            <ButtonLink href="/settings#ollama-models" variant="secondary" size="sm">
              Download more
            </ButtonLink>
          }
        >
          {models.length > 0 ? (
            <div className="grid gap-2 sm:grid-cols-2">
              {models.map((m) => (
                <SelectCard key={m.model} selected={model === m.model} onClick={() => setModel(m.model)}>
                  <div className="truncate pr-6 text-sm font-medium">{m.model}</div>
                  <div className="mt-0.5 truncate text-xs text-ink-3">
                    Ollama · {formatBytes(m.size_bytes)}
                    {m.model === catalog.default_model && " · the dataset's model"}
                  </div>
                </SelectCard>
              ))}
            </div>
          ) : (
            <Alert tone="warning">
              No Ollama models downloaded yet. The dataset was collected with {catalog.default_model}.{" "}
              <Link href="/settings#ollama-models" className="font-medium text-ink underline">
                Download it in Settings
              </Link>
              .
            </Alert>
          )}
        </Section>

        <Section
          title="Topologies"
          description="How MARBLE coordinates the agents. Every task is captured once under each, with the same agents and the same model."
        >
          <div className="grid gap-2 sm:grid-cols-2">
            {catalog.topologies.map((t) => {
              const on = topologies.includes(t.key);
              return (
                <SelectCard key={t.key} role="checkbox" selected={on} onClick={() => setTopologies((cur) => toggle(cur, t.key))}>
                  <div className="flex items-center gap-2 pr-6 text-sm font-medium">
                    {on && <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: variantColor(picked.findIndex((p) => p.key === t.key)) }} />}
                    {t.label}
                  </div>
                  <div className="mt-0.5 text-xs text-ink-3">MARBLE&apos;s {t.key} coordination</div>
                </SelectCard>
              );
            })}
          </div>
          {picked.length === 0 && <p className="mt-3 text-xs text-critical-text">Pick at least one topology.</p>}
        </Section>

        <Section
          title="Tasks"
          description="MARBLE task categories. Each task defines its own agents, usually 3 to 5."
          action={
            <div className="flex gap-1">
              <button
                type="button"
                onClick={() => setCategories(catalog.categories.filter((c) => !c.disabled && c.tasks.length > 0).map((c) => c.slug))}
                className={buttonClass("ghost", "sm")}
              >
                All
              </button>
              <button type="button" onClick={() => setCategories([])} className={buttonClass("ghost", "sm")}>
                None
              </button>
            </div>
          }
        >
          <div className="grid gap-2 sm:grid-cols-2">
            {catalog.categories.map((c) => {
              const off = c.disabled != null || c.tasks.length === 0;
              const on = categories.includes(c.slug);
              return off ? (
                <div key={c.slug} className="rounded-xl border border-hairline p-3">
                  <div className="text-sm font-medium text-ink-3">{c.label}</div>
                  <div className="mt-0.5 text-xs text-ink-3">{c.disabled ?? "No task configs found."}</div>
                </div>
              ) : (
                <SelectCard key={c.slug} role="checkbox" selected={on} onClick={() => setCategories((cur) => toggle(cur, c.slug))}>
                  <div className="pr-6 text-sm font-medium">{c.label}</div>
                  <div className="mt-0.5 text-xs text-ink-3 tabular-nums">{c.tasks.length} tasks</div>
                </SelectCard>
              );
            })}
          </div>
          {chosen.length === 0 && <p className="mt-3 text-xs text-critical-text">Pick at least one category.</p>}
          <div className="mt-5 grid gap-4 border-t border-hairline pt-5 sm:grid-cols-2">
            <Field
              label="Tasks per category"
              hint={`Tasks 1 to ${taskCount} of every chosen category. The dataset uses the first ${catalog.dataset_tasks}; these categories have up to ${maxTasks}.`}
            >
              <input
                type="number"
                min={1}
                max={maxTasks}
                value={taskCount}
                onChange={(e) => setPerCategory(Math.max(1, Number(e.target.value) || 1))}
                className={inputClass}
              />
            </Field>
            <Field label="Repeat each task" hint="Every repetition runs the task again and is its own capture.">
              <input
                type="number"
                min={1}
                max={999}
                value={repeat}
                onChange={(e) => setRepeat(Math.min(999, Math.max(1, Number(e.target.value) || 1)))}
                className={inputClass}
              />
            </Field>
          </div>
        </Section>

        <Section title="Hardware" description="Where Ollama runs the model. The agents themselves need no GPU.">
          {system.gpus.length === 0 ? (
            <Alert tone="warning">No NVIDIA GPU detected on this machine. Ollama runs the model on the CPU, which is slow.</Alert>
          ) : (
            <div className="space-y-3">
              <Segmented
                value={gpuMode}
                onChange={setGpuMode}
                options={[
                  { value: "auto", label: "Auto" },
                  { value: "manual", label: "Choose GPUs" },
                  { value: "cpu", label: "CPU" },
                ]}
              />
              {gpuMode !== "cpu" && (
                <div className="grid gap-2 sm:grid-cols-2">
                  {system.gpus.map((gpu) => {
                    const free = gpu.memory_total_mb != null && gpu.memory_used_mb != null ? gpu.memory_total_mb * 0.95 - gpu.memory_used_mb : null;
                    const body = (
                      <>
                        <div className="pr-6 text-sm font-medium">GPU {gpu.index}</div>
                        <div className="truncate text-xs text-ink-3">{gpu.name}</div>
                        <div className="mt-1 text-[11px] text-ink-3 tabular-nums">{free != null ? `${gb(Math.max(0, free))} free` : "Memory unknown"}</div>
                      </>
                    );
                    return gpuMode === "manual" ? (
                      <SelectCard
                        key={gpu.index}
                        role="checkbox"
                        selected={gpus.includes(gpu.index)}
                        onClick={() => setGpus((cur) => (cur.includes(gpu.index) ? cur.filter((g) => g !== gpu.index) : [...cur, gpu.index].sort((a, b) => a - b)))}
                      >
                        {body}
                      </SelectCard>
                    ) : (
                      <div key={gpu.index} className="rounded-xl border border-hairline p-3">
                        {body}
                      </div>
                    );
                  })}
                </div>
              )}
              {gpuMode === "manual" && gpus.length === 0 && <p className="text-xs text-critical-text">Select at least one GPU.</p>}
            </div>
          )}
          <div className="mt-5 grid gap-4 border-t border-hairline pt-5 sm:grid-cols-[10rem_1fr] sm:items-start">
            <Field label="Workers">
              <input
                type="number"
                min={1}
                max={16}
                value={workers}
                onChange={(e) => setWorkers(Math.min(16, Math.max(1, Number(e.target.value) || 1)))}
                className={inputClass}
              />
            </Field>
            <p className="text-xs text-ink-3 sm:pt-7">
              Each worker has its own Ollama, network and capture, and the tasks are divided between them. Workers that share a
              GPU slow each other down, which changes the timings you capture.
              {onGpu && needMb != null && ` Ollama needs about ${gb(needMb)} of GPU memory per worker for this model.`}
            </p>
          </div>
        </Section>
      </div>

      <aside className="space-y-4 lg:sticky lg:top-8">
        <div className="overflow-hidden rounded-2xl border border-hairline bg-surface shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
          <div className="border-b border-hairline px-5 py-5">
            <div className="text-xs font-medium text-ink-3">This run</div>
            <div className="mt-1 flex items-baseline gap-2">
              <span className="text-4xl font-semibold tracking-tight tabular-nums">{total.toLocaleString()}</span>
              <span className="text-sm text-ink-2">capture{total === 1 ? "" : "s"}</span>
            </div>
            <div className="mt-1 text-xs text-ink-3 tabular-nums">
              {chosen.length * taskCount} task{chosen.length * taskCount === 1 ? "" : "s"}
              {repeat > 1 && ` × ${repeat}`} × {picked.length} {picked.length === 1 ? "topology" : "topologies"}
            </div>
          </div>
          <dl className="divide-y divide-[var(--hairline)] px-5 text-sm">
            {[
              ["Model", model || "—"],
              ["Topologies", picked.map((t) => t.label).join(", ") || "—"],
              ["Tasks", `${taskCount} in each of ${chosen.length} categor${chosen.length === 1 ? "y" : "ies"}`],
              ["Repeat", repeat > 1 ? `× ${repeat}` : "Once"],
              ["Hardware", hardware],
              ["Workers", `${workerCount}`],
              ...(onGpu && needMb != null ? [["GPU memory", `~${gb(needMb * workerCount)}`]] : []),
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between gap-3 py-2.5">
                <dt className="shrink-0 text-ink-3">{k}</dt>
                <dd className="truncate font-medium">{v}</dd>
              </div>
            ))}
          </dl>
          <div className="space-y-3 border-t border-hairline p-5">
            <Field label="Name" hint="Optional. The run also gets a number (#1, #2, …); you can rename it later.">
              <input value={name} maxLength={60} onChange={(e) => setName(e.target.value)} placeholder="e.g. Graph and star, 15 tasks" className={inputClass} />
            </Field>
            {!system.docker.available && <Alert>{system.docker.error}</Alert>}
            {activeRuns.length > 0 && (
              <Alert tone="info">
                {activeRuns.length} run{activeRuns.length > 1 ? "s" : ""} in progress. This one starts right away if there is room,
                otherwise it waits in the queue.
              </Alert>
            )}
            {error && <Alert>{error}</Alert>}
            <button type="button" onClick={start} disabled={!canStart} className={`${buttonClass()} w-full`}>
              {starting && <Spinner />}
              Start experiment
            </button>
            <p className="text-xs text-ink-3">
              A task takes from a few seconds to five minutes. The first run builds the agents&apos; Docker image and pulls
              Ollama&apos;s, several GB in all. Containers, networks and the built image are removed when the run ends.
            </p>
          </div>
        </div>
      </aside>
    </div>
  );
}
