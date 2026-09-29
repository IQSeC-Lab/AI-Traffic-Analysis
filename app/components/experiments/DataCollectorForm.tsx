"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Box, Check, Cpu, Download, MessageSquareText, Play, Plus, SlidersHorizontal, Sparkles } from "lucide-react";

import {
  api,
  type LocalModel,
  type ModelsResponse,
  type Prompt,
  type PromptLibrary,
  type Run,
  type RunConfig,
  type SystemInfo,
} from "@/lib/api";
import { runHref } from "@/lib/experiments";
import { formatBytes } from "@/lib/format";
import { Alert, ButtonLink, Field, Loading, Segmented, Spinner, buttonClass, inputClass } from "@/components/ui";
import { PromptDialog } from "@/components/prompts/PromptDialog";

// What the experiment API accepts as `model`: the repo id when known, else the folder name.
const modelRef = (m: LocalModel) => m.model ?? m.folder;

function Section({
  icon: Icon,
  title,
  description,
  action,
  children,
}: {
  icon: typeof Box;
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-hairline bg-surface p-5 shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-2 text-ink-2">
            <Icon className="h-4 w-4" strokeWidth={1.75} />
          </div>
          <div>
            <h2 className="text-sm font-semibold">{title}</h2>
            {description && <p className="text-xs text-ink-3">{description}</p>}
          </div>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function SelectCard({
  selected,
  onClick,
  children,
  role = "radio",
}: {
  selected: boolean;
  onClick: () => void;
  children: ReactNode;
  role?: "radio" | "checkbox";
}) {
  return (
    <button
      type="button"
      role={role}
      aria-checked={selected}
      onClick={onClick}
      className={`relative w-full rounded-xl border p-3 text-left transition-all ${
        selected
          ? "border-accent bg-accent-wash/60 ring-4 ring-accent/10"
          : "border-hairline hover:border-axis hover:bg-surface-2/50"
      }`}
    >
      <span
        className={`absolute top-3 right-3 flex h-4 w-4 items-center justify-center ${role === "radio" ? "rounded-full" : "rounded"} border ${
          selected ? "border-accent-strong bg-accent-strong text-white" : "border-axis"
        }`}
      >
        {selected && <Check className="h-3 w-3" strokeWidth={3} />}
      </span>
      {children}
    </button>
  );
}

export function DataCollectorForm() {
  const router = useRouter();
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [models, setModels] = useState<LocalModel[] | null>(null);
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [activeRuns, setActiveRuns] = useState<Run[]>([]);

  const [model, setModel] = useState("");
  const [gpuMode, setGpuMode] = useState<"auto" | "manual" | "cpu">("auto");
  const [gpus, setGpus] = useState<number[]>([]); // when choosing GPUs by hand
  const [workers, setWorkers] = useState(1);
  const [name, setName] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [repeat, setRepeat] = useState(1);
  const [maxTokens, setMaxTokens] = useState(2048);

  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    Promise.all([
      api<SystemInfo>("/system"),
      api<ModelsResponse>("/settings/models"),
      api<PromptLibrary>("/prompts"),
      api<Run[]>("/data-collector/active"),
    ])
      .then(([sys, downloaded, library, active]) => {
        const ready = downloaded.models.filter((m) => m.complete && !m.downloading);
        setSystem(sys);
        setModels(ready);
        setModel(ready[0] ? modelRef(ready[0]) : "");
        setGpuMode(sys.gpus.length > 0 ? "auto" : "cpu");
        setGpus(sys.gpus.length > 0 ? [sys.gpus[0].index] : []);
        setPrompts(library.prompts);
        setSelected(new Set(library.prompts.map((p) => p.number)));
        setActiveRuns(active);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  const categories = useMemo(() => {
    const groups = new Map<string, Prompt[]>();
    for (const p of prompts) {
      groups.set(p.category, [...(groups.get(p.category) ?? []), p]);
    }
    return [...groups.entries()];
  }, [prompts]);

  function toggleGpu(index: number) {
    setGpus((current) =>
      current.includes(index) ? current.filter((g) => g !== index) : [...current, index].sort((a, b) => a - b),
    );
  }

  function togglePrompts(numbers: number[]) {
    setSelected((current) => {
      const next = new Set(current);
      const allOn = numbers.every((n) => next.has(n));
      numbers.forEach((n) => (allOn ? next.delete(n) : next.add(n)));
      return next;
    });
  }

  async function start() {
    setStarting(true);
    setError(null);
    const config: Partial<RunConfig> = {
      model,
      gpus: gpuMode === "auto" ? "auto" : gpuMode === "cpu" ? [] : gpus,
      workers,
      name: name.trim() || null,
      prompts: selected.size === prompts.length ? null : [...selected].sort((a, b) => a - b),
      repeat: repeat > 1 ? repeat : null,
      max_tokens: maxTokens,
    };
    try {
      const run = await api<Run>("/data-collector/runs", { method: "POST", body: JSON.stringify(config) });
      router.push(runHref(run.id));
    } catch (e) {
      setError((e as Error).message);
      setStarting(false);
    }
  }

  if (!system || !models) {
    return error ? <Alert>{error}</Alert> : <Loading label="Detecting GPUs and models…" />;
  }

  const total = selected.size * Math.max(1, repeat);
  const needMb = models.find((m) => modelRef(m) === model)?.gpu_memory_mb ?? null;
  const onGpu = gpuMode !== "cpu" && system.gpus.length > 0;
  const hardware = !onGpu ? "CPU" : gpuMode === "auto" ? "Auto GPU" : gpus.length ? `GPU ${gpus.join(", ")}` : "—";
  // Workers slow each other down when they share a device (all on the CPU, or split over the same GPUs).
  const sharedDevice = workers > 1 && (!onGpu || gpuMode === "manual");
  const gb = (mb: number) => `${(mb / 1024).toFixed(1)} GB`;
  const canStart =
    system.docker.available && model && selected.size > 0 && !starting && !(onGpu && gpuMode === "manual" && gpus.length === 0);
  const selectedCategories = categories.filter(([, items]) => items.some((p) => selected.has(p.number))).length;

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[1fr_20rem]">
      <div className="space-y-6">
        <Section
          icon={Box}
          title="Model"
          description="Models downloaded on this machine."
          action={
            <ButtonLink href="/settings#models" variant="secondary" size="sm">
              <Download className="h-3.5 w-3.5" /> Download more
            </ButtonLink>
          }
        >
          {models.length > 0 ? (
            <div className="grid gap-2 sm:grid-cols-2">
              {models.map((m) => (
                <SelectCard key={m.folder} selected={model === modelRef(m)} onClick={() => setModel(modelRef(m))}>
                  <div className="truncate pr-6 text-sm font-medium">{modelRef(m).split("/").pop()}</div>
                  <div className="mt-0.5 truncate text-xs text-ink-3">
                    {m.model?.split("/")[0] ?? "local"} · {formatBytes(m.size_bytes)}
                  </div>
                </SelectCard>
              ))}
            </div>
          ) : (
            <Alert tone="warning">
              No models downloaded yet.{" "}
              <Link href="/settings#models" className="font-medium text-ink underline">
                Download one in Settings
              </Link>
              .
            </Alert>
          )}
        </Section>

        <Section icon={Cpu} title="Hardware" description="Where the model runs, and how many copies of it work through the prompts in parallel.">
          {system.gpus.length === 0 ? (
            <Alert tone="warning">
              No NVIDIA GPU detected on this machine. The model runs on the CPU, which is very slow for large models.
            </Alert>
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
              <p className="text-xs text-ink-3">
                {gpuMode === "auto" &&
                  "Each worker goes to the GPU with the most free memory. If none has room, the run waits in the queue and starts on its own."}
                {gpuMode === "manual" && "Each worker splits the model across the GPUs you select. Select several to fit a large model."}
                {gpuMode === "cpu" && "Runs on the CPU. CPU runs go one at a time, so they don't slow each other down."}
              </p>
              {gpuMode !== "cpu" && (
                <div className="grid gap-2 sm:grid-cols-2">
                  {system.gpus.map((gpu) => {
                    const total = gpu.memory_total_mb;
                    const usedMb = gpu.memory_used_mb;
                    const free = total != null && usedMb != null ? total * 0.95 - usedMb : null;
                    const room = free != null && needMb ? Math.max(0, Math.floor(free / needMb)) : null;
                    const body = (
                      <>
                        <div className="pr-6 text-sm font-medium">GPU {gpu.index}</div>
                        <div className="truncate text-xs text-ink-3">{gpu.name}</div>
                        <div className="mt-2.5 h-1 overflow-hidden rounded-full bg-accent-wash">
                          <div
                            className="h-full rounded-full bg-accent"
                            style={{ width: `${total && usedMb != null ? (usedMb / total) * 100 : 0}%` }}
                          />
                        </div>
                        <div className="mt-1 flex justify-between gap-2 text-[11px] text-ink-3 tabular-nums">
                          <span>{free != null ? `${gb(Math.max(0, free))} free` : "Memory unknown"}</span>
                          {room != null && <span>room for {room} now</span>}
                        </div>
                      </>
                    );
                    return gpuMode === "manual" ? (
                      <SelectCard key={gpu.index} role="checkbox" selected={gpus.includes(gpu.index)} onClick={() => toggleGpu(gpu.index)}>
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
            <div className="space-y-1.5 text-xs text-ink-3 sm:pt-7">
              <p>
                Each worker runs its own copy of the model with its own packet capture, and they share the prompts
                {workers > 1 ? `, so ${workers} workers finish up to ${workers}× sooner.` : ". Add workers to finish sooner."}
              </p>
              {onGpu && needMb != null && (
                <p>
                  Needs about <span className="font-medium text-ink-2">{gb(needMb)}</span> of GPU memory per worker
                  {workers > 1 && (
                    <>
                      , <span className="font-medium text-ink-2">{gb(needMb * workers)}</span> in total
                    </>
                  )}
                  .
                </p>
              )}
              {sharedDevice && (
                <p className="text-ink-2">
                  These workers share the same {onGpu ? "GPUs" : "CPU"}, so they slow each other down, which changes the
                  timings you capture.
                </p>
              )}
            </div>
          </div>
        </Section>

        <Section
          icon={MessageSquareText}
          title="Prompts"
          description="Click a category to toggle it. Hover a number to preview the prompt."
          action={
            <div className="flex gap-1">
              <button type="button" onClick={() => setAdding(true)} className={buttonClass("secondary", "sm")}>
                <Plus className="h-3.5 w-3.5" /> New prompt
              </button>
              <button type="button" onClick={() => setSelected(new Set(prompts.map((p) => p.number)))} className={buttonClass("ghost", "sm")}>
                All
              </button>
              <button type="button" onClick={() => setSelected(new Set())} className={buttonClass("ghost", "sm")}>
                None
              </button>
            </div>
          }
        >
          <div className="space-y-2.5">
            {categories.map(([name, items]) => {
              const count = items.filter((p) => selected.has(p.number)).length;
              return (
                <div key={name} className="flex flex-col gap-2 sm:flex-row sm:items-center">
                  <button
                    type="button"
                    onClick={() => togglePrompts(items.map((p) => p.number))}
                    className="flex w-60 shrink-0 items-center justify-between gap-2 rounded-lg px-2 py-1 text-left text-xs font-medium text-ink-2 hover:bg-surface-2"
                  >
                    <span className="truncate">{name}</span>
                    <span className="text-ink-3 tabular-nums">
                      {count}/{items.length}
                    </span>
                  </button>
                  <div className="flex flex-wrap gap-1">
                    {items.map((p) => (
                      <button
                        key={p.number}
                        type="button"
                        title={p.text.slice(0, 300)}
                        onClick={() => togglePrompts([p.number])}
                        className={`h-7 w-8 rounded-md text-xs font-medium tabular-nums transition-colors ${
                          selected.has(p.number)
                            ? "bg-accent-strong text-white shadow-sm"
                            : "bg-surface-2 text-ink-3 hover:text-ink"
                        }`}
                      >
                        {p.number}
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </Section>

        <Section icon={SlidersHorizontal} title="Generation">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Repeat each prompt" hint="Every repetition gets a fresh container and its own PCAP.">
              <input
                type="number"
                min={1}
                value={repeat}
                onChange={(e) => setRepeat(Math.max(1, Number(e.target.value) || 1))}
                className={inputClass}
              />
            </Field>
            <Field label="Max tokens" hint="Maximum tokens generated per prompt.">
              <input
                type="number"
                min={1}
                value={maxTokens}
                onChange={(e) => setMaxTokens(Math.max(1, Number(e.target.value) || 1))}
                className={inputClass}
              />
            </Field>
          </div>
        </Section>
      </div>

      <aside className="space-y-4 lg:sticky lg:top-8">
        <div className="overflow-hidden rounded-2xl border border-hairline bg-surface shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
          <div
            className="px-5 py-5 text-white"
            style={{ background: "var(--brand-gradient)" }}
          >
            <div className="flex items-center gap-1.5 text-xs font-medium text-white/80">
              <Sparkles className="h-3.5 w-3.5" /> This run
            </div>
            <div className="mt-2 text-4xl font-semibold tracking-tight">{total.toLocaleString()}</div>
            <div className="text-sm text-white/80">capture{total === 1 ? "" : "s"}</div>
          </div>
          <dl className="divide-y divide-[var(--hairline)] px-5 text-sm">
            {[
              ["Model", model ? model.split("/").pop() : "—"],
              ["Hardware", hardware],
              ["Workers", `${workers}`],
              ...(onGpu && needMb != null ? [["GPU memory", `~${gb(needMb * workers)}`]] : []),
              ["Prompts", `${selected.size} from ${selectedCategories} categor${selectedCategories === 1 ? "y" : "ies"}`],
              ["Repeat", repeat > 1 ? `× ${repeat}` : "Once"],
              ["Max tokens", maxTokens.toLocaleString()],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between gap-3 py-2.5">
                <dt className="text-ink-3">{k}</dt>
                <dd className="truncate font-medium">{v}</dd>
              </div>
            ))}
          </dl>
          <div className="space-y-3 border-t border-hairline p-5">
            <Field label="Name" hint="Optional. The run also gets a number (#1, #2, …); you can rename it later.">
              <input
                value={name}
                maxLength={60}
                onChange={(e) => setName(e.target.value)}
                placeholder={model ? `${model.split("/").pop()} baseline` : "e.g. Qwen baseline"}
                className={inputClass}
              />
            </Field>
            {!system.docker.available && <Alert>{system.docker.error}</Alert>}
            {activeRuns.length > 0 && (
              <Alert tone="info">
                {activeRuns.length} run{activeRuns.length > 1 ? "s" : ""} in progress. This one starts right away if there is
                room, otherwise it waits in the queue.
              </Alert>
            )}
            {error && <Alert>{error}</Alert>}
            <button type="button" onClick={start} disabled={!canStart} className={`${buttonClass()} w-full`}>
              {starting ? <Spinner /> : <Play className="h-4 w-4" />}
              Start experiment
            </button>
            <p className="text-xs text-ink-3">Containers, network and images created by the run are removed when it ends.</p>
          </div>
        </div>
      </aside>

      {adding && (
        <PromptDialog
          categories={categories.map(([name]) => name)}
          onSaved={(p) => {
            // New prompts join the library and are selected for this run.
            setPrompts((cur) => [...cur, p]);
            setSelected((cur) => new Set(cur).add(p.number));
          }}
          onClose={() => setAdding(false)}
        />
      )}
    </div>
  );
}
