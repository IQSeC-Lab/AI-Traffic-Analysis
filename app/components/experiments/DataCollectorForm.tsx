"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Check } from "lucide-react";

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
  title,
  description,
  action,
  children,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-hairline bg-surface p-5 shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">{title}</h2>
          {description && <p className="text-xs text-ink-3">{description}</p>}
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
      className={`relative w-full rounded-xl border p-3 text-left transition-colors ${
        selected
          ? "border-accent bg-accent-wash/60"
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
  const [split, setSplit] = useState(false); // chosen GPUs: split one copy across them instead of one copy each
  const [workers, setWorkers] = useState(1); // Auto, CPU, or split
  const [perGpu, setPerGpu] = useState(1); // chosen GPUs, one copy each: workers on every GPU
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
        // Several GPUs: one copy of the model on each, dividing the prompts, unless the user picks otherwise
        setGpuMode(sys.gpus.length > 1 ? "manual" : sys.gpus.length > 0 ? "auto" : "cpu");
        setGpus(sys.gpus.map((g) => g.index));
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

  const onGpu = gpuMode !== "cpu" && (system?.gpus.length ?? 0) > 0;
  const splitting = onGpu && gpuMode === "manual" && split && gpus.length > 1;
  const perGpuMode = onGpu && gpuMode === "manual" && !splitting;
  // The API also caps workers at the number of captures: a worker without prompts would only hold memory
  const workerCount = Math.max(
    1,
    Math.min(perGpuMode ? Math.max(1, gpus.length) * perGpu : workers, selected.size * Math.max(1, repeat)),
  );

  async function start() {
    setStarting(true);
    setError(null);
    const config: Partial<RunConfig> = {
      model,
      gpus: !onGpu ? [] : gpuMode === "auto" ? "auto" : gpus,
      split_model: splitting,
      workers: workerCount,
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
  const gb = (mb: number) => `${(mb / 1024).toFixed(1)} GB`;
  const hardware = !onGpu
    ? "CPU"
    : gpuMode === "auto"
      ? "Auto GPU"
      : gpus.length
        ? `GPU ${gpus.join(", ")}${splitting ? " · split" : ""}`
        : "—";
  // How the captures are divided: worker k gets every n-th one, so shares differ by at most one.
  const shares = Array.from({ length: workerCount }, (_, k) => Math.floor(total / workerCount) + (k < total % workerCount ? 1 : 0));
  const shareText = shares.length && shares[0] !== shares[shares.length - 1] ? `${shares[shares.length - 1]}–${shares[0]}` : `${shares[0] ?? 0}`;
  const workerWhere = (k: number) =>
    !onGpu ? "CPU" : gpuMode === "auto" ? "GPU auto" : splitting ? `GPU ${gpus.join("+")}` : `GPU ${gpus[k % gpus.length]}`;
  // Workers slow each other down when they share a device
  const sharedDevice =
    workerCount > 1 &&
    (!onGpu || splitting || (perGpuMode && perGpu > 1) || (gpuMode === "auto" && workerCount > system.gpus.length));
  // GPU memory each chosen GPU needs, and chosen GPUs the model can't fit on alone
  const perGpuNeed = needMb == null ? null : perGpuMode ? needMb * perGpu : splitting ? (needMb * workerCount) / gpus.length : needMb;
  const tooSmall = perGpuMode && needMb != null
    ? system.gpus.filter((g) => gpus.includes(g.index) && g.memory_total_mb != null && needMb > g.memory_total_mb * 0.95)
    : [];
  const canStart =
    system.docker.available && model && selected.size > 0 && !starting && !(onGpu && gpuMode === "manual" && gpus.length === 0);
  const selectedCategories = categories.filter(([, items]) => items.some((p) => selected.has(p.number))).length;

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[1fr_20rem]">
      <div className="space-y-6">
        <Section
          title="Model"
          description="Models downloaded on this machine."
          action={
            <ButtonLink href="/settings#models" variant="secondary" size="sm">
              Download more
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

        <Section
          title="Hardware"
          description="Where the model runs, and how many copies of it divide the prompts between them."
        >
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
                  "Workers are spread over the GPUs with free memory. If none has room, the run waits in the queue and starts on its own."}
                {gpuMode === "manual" &&
                  (splitting
                    ? "Every worker's model is split across all the selected GPUs. Use this when the model doesn't fit on one GPU."
                    : "Each selected GPU runs its own copy of the model, with its own containers, network and capture, and the prompts are divided between them.")}
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
              {gpuMode === "manual" && gpus.length > 1 && (
                <div className="flex flex-wrap items-center gap-2 pt-1">
                  <span className="text-xs font-medium text-ink-2">Use the selected GPUs</span>
                  <Segmented
                    value={split ? "split" : "each"}
                    onChange={(v) => setSplit(v === "split")}
                    options={[
                      { value: "each", label: "One copy per GPU" },
                      { value: "split", label: "Split one copy across them" },
                    ]}
                  />
                </div>
              )}
              {tooSmall.length > 0 && needMb != null && (
                <Alert tone="warning">
                  The model needs about {gb(needMb)}, more than GPU {tooSmall.map((g) => g.index).join(", ")} can hold on
                  its own.{" "}
                  {gpus.length > 1 ? (
                    <button type="button" onClick={() => setSplit(true)} className="font-medium text-ink underline">
                      Split it across the selected GPUs
                    </button>
                  ) : (
                    "Select more GPUs and split it across them."
                  )}
                </Alert>
              )}
            </div>
          )}

          <div className="mt-5 grid gap-4 border-t border-hairline pt-5 sm:grid-cols-[10rem_1fr] sm:items-start">
            {perGpuMode ? (
              <Field label="Workers per GPU">
                <input
                  type="number"
                  min={1}
                  max={16}
                  value={perGpu}
                  onChange={(e) => setPerGpu(Math.min(16, Math.max(1, Number(e.target.value) || 1)))}
                  className={inputClass}
                />
              </Field>
            ) : (
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
            )}
            <div className="space-y-1.5 text-xs text-ink-3 sm:pt-7">
              <p>
                Each worker runs its own copy of the model with its own containers, network and packet capture.
                {workerCount > 1
                  ? ` The prompts are divided between them: ${total} capture${total === 1 ? "" : "s"} over ${workerCount} workers is ${shareText} each, so they finish up to ${workerCount}× sooner.`
                  : gpuMode === "auto" && system.gpus.length > 1
                    ? ` With ${system.gpus.length} workers, each GPU runs its own copy and the prompts are divided between them.`
                    : " Add workers to finish sooner."}
              </p>
              {onGpu && perGpuNeed != null && (
                <p>
                  Needs about <span className="font-medium text-ink-2">{gb(perGpuNeed)}</span> of GPU memory
                  {gpuMode === "auto" ? " per worker" : " on each selected GPU"}
                  {workerCount > 1 && needMb != null && (
                    <>
                      , <span className="font-medium text-ink-2">{gb(needMb * workerCount)}</span> in total
                    </>
                  )}
                  .
                </p>
              )}
              {sharedDevice && (
                <p className="text-ink-2">
                  Some workers share {onGpu ? "a GPU" : "the CPU"}, so they slow each other down, which changes the
                  timings you capture.
                </p>
              )}
            </div>
          </div>

          {workerCount > 1 && total > 0 && (
            <div className="mt-4 flex flex-wrap gap-1.5">
              {shares.map((n, k) => (
                <span
                  key={k}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-hairline bg-surface-2/50 px-2 py-1 text-[11px] text-ink-3 tabular-nums"
                >
                  <span className="font-medium text-ink-2">w{k + 1}</span>
                  {workerWhere(k)}
                  <span className="text-ink-2">· {n}</span>
                </span>
              ))}
            </div>
          )}
        </Section>

        <Section
          title="Prompts"
          description="Click a category to toggle it. Hover a number to preview the prompt."
          action={
            <div className="flex gap-1">
              <button type="button" onClick={() => setAdding(true)} className={buttonClass("secondary", "sm")}>
                New prompt
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

        <Section title="Generation">
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
          <div className="border-b border-hairline px-5 py-5">
            <div className="text-xs font-medium text-ink-3">This run</div>
            <div className="mt-1 flex items-baseline gap-2">
              <span className="text-4xl font-semibold tracking-tight tabular-nums">{total.toLocaleString()}</span>
              <span className="text-sm text-ink-2">capture{total === 1 ? "" : "s"}</span>
            </div>
          </div>
          <dl className="divide-y divide-[var(--hairline)] px-5 text-sm">
            {[
              ["Model", model ? model.split("/").pop() : "—"],
              ["Hardware", hardware],
              ["Workers", workerCount > 1 ? `${workerCount} · ${shareText} captures each` : "1"],
              ...(onGpu && needMb != null ? [["GPU memory", `~${gb(needMb * workerCount)}`]] : []),
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
              {starting && <Spinner />}
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
