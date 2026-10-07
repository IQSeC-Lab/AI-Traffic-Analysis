"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Check, X } from "lucide-react";

import {
  DISTRIBUTIONS,
  api,
  modelRef,
  type LocalModel,
  type ModelsResponse,
  type NetworkCondition,
  type OllamaModel,
  type OllamaModelsResponse,
  type Prompt,
  type PromptLibrary,
  type Run,
  type RunConfig,
  type Settings,
  type SystemInfo,
} from "@/lib/api";
import { EXPERIMENTS, MAX_VARIANTS, runHref } from "@/lib/experiments";
import { conditionLabel, formatBytes } from "@/lib/format";
import { Alert, ButtonLink, Field, Loading, Segmented, Spinner, buttonClass, inputClass } from "@/components/ui";
import { PromptDialog } from "@/components/prompts/PromptDialog";
import { CustomPromptsEditor } from "./CustomPromptsEditor";
import { Section } from "./FormSection";
import { variantColor } from "./RunBadge";
import { ScenariosEditor, newScenario, scenarioProblem, toScenario, type ScenarioDraft } from "./ScenariosEditor";

const TEMPERATURE_PRESETS = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1, 1.2, 1.5, 2];
// 6-Delay's r1.py used 500 ms with 50 ms of jitter; no delay is the baseline to compare against.
const DEFAULT_CONDITIONS: NetworkCondition[] = [
  { delay_ms: 0, jitter_ms: 0, distribution: "normal" },
  { delay_ms: 500, jitter_ms: 50, distribution: "normal" },
];

/** Why a network condition can't run, if it can't: jitter without delay, or a duplicate of an earlier one. */
function conditionProblem(conditions: NetworkCondition[], i: number): string | null {
  const c = conditions[i];
  if (c.jitter_ms && !c.delay_ms) return "Jitter needs a delay.";
  const same = conditions.findIndex((o) => conditionLabel(o) === conditionLabel(c));
  return same < i ? `Same as condition ${same + 1}.` : null;
}

export function SelectCard({
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

export function RunForm({ experiment }: { experiment: string }) {
  const router = useRouter();
  const info = EXPERIMENTS.find((e) => e.slug === experiment);
  const multiModel = experiment === "scalability";
  const byScenario = info?.scenarios ?? false; // Custom Experiment: each scenario has its own model, temperature and network
  const writesPrompts = info?.ownPrompts ?? false; // Custom Prompts: written here, not chosen from the library
  const sweepsTemperature = experiment === "temperature-change";
  const setsTemperature = sweepsTemperature || byScenario; // instead of sampling at the default in Settings
  const picksProvider = experiment === "data-collector"; // the app's own server, or Ollama
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [models, setModels] = useState<LocalModel[] | null>(null);
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [activeRuns, setActiveRuns] = useState<Run[]>([]);

  const [model, setModel] = useState("");
  const [provider, setProvider] = useState<"transformers" | "ollama">("transformers");
  const [ollamaModels, setOllamaModels] = useState<OllamaModel[]>([]);
  const [ollamaModel, setOllamaModel] = useState("");
  const onOllama = picksProvider && provider === "ollama";
  const [modelsChosen, setModelsChosen] = useState<string[]>([]); // Scalability: the models compared
  const [temperatures, setTemperatures] = useState<number[]>([0.3, 0.7, 0.9]);
  const [customTemperature, setCustomTemperature] = useState("");
  const [conditions, setConditions] = useState<NetworkCondition[]>(DEFAULT_CONDITIONS);
  const [scenarios, setScenarios] = useState<ScenarioDraft[]>([]); // Custom Experiment
  // Custom Experiment: prompts from the library, or written for it as in Custom Prompts
  const [promptSource, setPromptSource] = useState<"library" | "written">("library");
  const ownPrompts = writesPrompts || (byScenario && promptSource === "written");
  const [gpuMode, setGpuMode] = useState<"auto" | "manual" | "cpu">("auto");
  const [gpus, setGpus] = useState<number[]>([]); // when choosing GPUs by hand
  const [split, setSplit] = useState(false); // chosen GPUs: split one copy across them instead of one copy each
  const [workers, setWorkers] = useState(1); // Auto, CPU, or split
  const [perGpu, setPerGpu] = useState(1); // chosen GPUs, one copy each: workers on every GPU
  const [name, setName] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [repeat, setRepeat] = useState(info?.defaults?.repeat ?? 1);
  const [maxTokens, setMaxTokens] = useState(2048);

  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [customPrompts, setCustomPrompts] = useState<string[] | null>(null); // null while they load
  const [defaultTemperature, setDefaultTemperature] = useState<number | null>(null);

  useEffect(() => {
    Promise.all([
      api<SystemInfo>("/system"),
      api<ModelsResponse>("/settings/models"),
      // Custom Prompts never reads the prompt library
      writesPrompts ? Promise.resolve<PromptLibrary>({ prompts: [], categories: [] }) : api<PromptLibrary>("/prompts"),
      api<Run[]>("/experiments/active"),
      api<Settings>("/settings"),
      picksProvider ? api<OllamaModelsResponse>("/settings/ollama-models") : Promise.resolve(null),
    ])
      .then(([sys, downloaded, library, active, settings, ollama]) => {
        const pulled = ollama?.models.filter((m) => m.complete && !m.downloading) ?? [];
        setOllamaModels(pulled);
        setOllamaModel(pulled[0]?.model ?? "");
        const ready = downloaded.models.filter((m) => m.complete && !m.downloading);
        // Scalability goes from the smallest model to the largest, so its charts read that way too
        if (multiModel) ready.sort((a, b) => a.size_bytes - b.size_bytes);
        setSystem(sys);
        setModels(ready);
        setModel(ready[0] ? modelRef(ready[0]) : "");
        setModelsChosen(ready[0] ? [modelRef(ready[0])] : []);
        setScenarios([newScenario(ready[0] ? modelRef(ready[0]) : "", settings.default_temperature)]);
        // Several GPUs: one copy of the model on each, dividing the prompts, unless the user picks otherwise
        setGpuMode(sys.gpus.length > 1 ? "manual" : sys.gpus.length > 0 ? "auto" : "cpu");
        setGpus(sys.gpus.map((g) => g.index));
        setPrompts(library.prompts);
        // The original experiment's prompts when it used one category, otherwise all of them
        const category = info?.defaults?.category;
        const preset = library.prompts.filter((p) => p.category === category);
        setSelected(new Set((preset.length ? preset : library.prompts).map((p) => p.number)));
        setActiveRuns(active);
        setDefaultTemperature(settings.default_temperature);
      })
      .catch((e: Error) => setError(e.message));
  }, [multiModel, writesPrompts, picksProvider, info]);

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

  function toggleModel(ref: string) {
    // Kept in list order (smallest first), which is the order the run compares them in
    setModelsChosen((current) =>
      current.includes(ref)
        ? current.filter((m) => m !== ref)
        : (models ?? []).map(modelRef).filter((m) => m === ref || current.includes(m)),
    );
  }

  function toggleTemperature(t: number) {
    setTemperatures((current) =>
      current.includes(t) ? current.filter((x) => x !== t) : [...current, t].sort((a, b) => a - b),
    );
  }

  function addCustomTemperature() {
    const t = Math.round(Number(customTemperature) * 100) / 100;
    if (customTemperature.trim() === "" || !(t >= 0 && t <= 2)) return;
    if (!temperatures.includes(t)) toggleTemperature(t);
    setCustomTemperature("");
  }

  function updateCondition(i: number, change: Partial<NetworkCondition>) {
    setConditions((current) => current.map((c, j) => (j === i ? { ...c, ...change } : c)));
  }

  function togglePrompts(numbers: number[]) {
    setSelected((current) => {
      const next = new Set(current);
      const allOn = numbers.every((n) => next.has(n));
      numbers.forEach((n) => (allOn ? next.delete(n) : next.add(n)));
      return next;
    });
  }

  // How many temperatures, models, network conditions or scenarios: every prompt is captured once per variant
  const variantCount = byScenario
    ? scenarios.length
    : experiment === "temperature-change"
      ? temperatures.length
      : multiModel
        ? modelsChosen.length
        : experiment === "delay"
          ? conditions.length
          : 1;
  const variantsOk =
    variantCount >= 1 &&
    variantCount <= MAX_VARIANTS &&
    (experiment !== "delay" || conditions.every((_, i) => !conditionProblem(conditions, i))) &&
    (!byScenario || scenarios.every((_, i) => !scenarioProblem(scenarios, i)));

  const promptCount = ownPrompts ? (customPrompts?.length ?? 0) : selected.size;
  const promptsOk = ownPrompts
    ? customPrompts != null && customPrompts.length > 0 && customPrompts.every((p) => p.trim())
    : selected.size > 0;

  const onGpu = gpuMode !== "cpu" && (system?.gpus.length ?? 0) > 0;
  const splitting = onGpu && gpuMode === "manual" && split && gpus.length > 1;
  const perGpuMode = onGpu && gpuMode === "manual" && !splitting;
  // The API also caps workers at the number of captures: a worker without prompts would only hold memory
  const workerCount = Math.max(
    1,
    Math.min(perGpuMode ? Math.max(1, gpus.length) * perGpu : workers, promptCount * Math.max(1, repeat) * Math.max(1, variantCount)),
  );

  async function start() {
    setStarting(true);
    setError(null);
    const config: Partial<RunConfig> = {
      ...(byScenario
        ? { scenarios: scenarios.map(toScenario), prompt_source: promptSource }
        : multiModel
          ? { models: modelsChosen }
          : onOllama
            ? { model: ollamaModel, provider }
            : { model }),
      ...(experiment === "temperature-change" && { temperatures }),
      ...(experiment === "delay" && { conditions }),
      gpus: !onGpu ? [] : gpuMode === "auto" ? "auto" : gpus,
      split_model: splitting,
      workers: workerCount,
      name: name.trim() || null,
      ...(ownPrompts
        ? { prompt_texts: customPrompts ?? [], prompts: null }
        : { prompts: selected.size === prompts.length ? null : [...selected].sort((a, b) => a - b) }),
      repeat: repeat > 1 ? repeat : null,
      max_tokens: maxTokens,
    };
    try {
      const run = await api<Run>(`/${experiment}/runs`, { method: "POST", body: JSON.stringify(config) });
      router.push(runHref(run));
    } catch (e) {
      setError((e as Error).message);
      setStarting(false);
    }
  }

  if (!system || !models) {
    return error ? <Alert>{error}</Alert> : <Loading label="Detecting GPUs and models…" />;
  }

  const total = promptCount * Math.max(1, repeat) * variantCount;
  // Workers load one model at a time, so a run of several reserves room for the largest
  const modelRefs = byScenario ? scenarios.map((s) => s.model) : multiModel ? modelsChosen : [model];
  const chosen = models.filter((m) => modelRefs.includes(modelRef(m)));
  const severalModels = chosen.length > 1;
  const needMb = onOllama
    ? (ollamaModels.find((m) => m.model === ollamaModel)?.gpu_memory_mb ?? null)
    : chosen.some((m) => m.gpu_memory_mb != null)
      ? Math.max(...chosen.map((m) => m.gpu_memory_mb ?? 0))
      : null;
  const shortName = (ref: string) => ref.split("/").pop() ?? ref;
  const modelText = onOllama
    ? ollamaModel || "—"
    : chosen.length === 1
      ? shortName(modelRef(chosen[0]))
      : multiModel || severalModels
        ? `${chosen.length} models`
        : "—";
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
    system.docker.available &&
    (byScenario || (multiModel ? modelsChosen.length > 0 : onOllama ? ollamaModel : model)) &&
    variantsOk &&
    promptsOk &&
    !starting &&
    !(onGpu && gpuMode === "manual" && gpus.length === 0);
  const selectedCategories = categories.filter(([, items]) => items.some((p) => selected.has(p.number))).length;
  // Custom Experiment: shown at the top of whichever prompts section is open
  const promptSourceToggle = byScenario && (
    <div className="mb-4">
      <Segmented
        value={promptSource}
        onChange={setPromptSource}
        options={[
          { value: "library", label: "From the prompt library" },
          { value: "written", label: "Written here" },
        ]}
      />
    </div>
  );

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[1fr_20rem]">
      <div className="space-y-6">
        {byScenario ? (
          <ScenariosEditor scenarios={scenarios} onChange={setScenarios} models={models} />
        ) : (
          <Section
            title={multiModel ? "Models" : "Model"}
            description={
              multiModel
                ? `Models downloaded on this machine, smallest first. Pick up to ${MAX_VARIANTS}: every one gets the same prompts, so the model is the only thing that changes.`
                : onOllama
                  ? "Ollama models downloaded on this machine, served by Ollama instead of the app's own server."
                  : "Models downloaded on this machine."
            }
            action={
              <ButtonLink href={onOllama ? "/settings#ollama-models" : "/settings#models"} variant="secondary" size="sm">
                Download more
              </ButtonLink>
            }
          >
            {picksProvider && (
              <div className="mb-4 flex flex-wrap items-center gap-3">
                <span className="text-xs font-medium text-ink-2">Provider</span>
                <Segmented
                  value={provider}
                  onChange={setProvider}
                  options={[
                    { value: "transformers", label: "Hugging Face" },
                    { value: "ollama", label: "Ollama" },
                  ]}
                />
                <span className="text-xs text-ink-3">
                  {onOllama
                    ? "Ollama serves the model. Same prompts, network and capture."
                    : "The app's own server loads the model with transformers, as in the original experiment."}
                </span>
              </div>
            )}
            {onOllama ? (
              ollamaModels.length > 0 ? (
                <div className="grid gap-2 sm:grid-cols-2">
                  {ollamaModels.map((m) => (
                    <SelectCard key={m.model} selected={ollamaModel === m.model} onClick={() => setOllamaModel(m.model)}>
                      <div className="truncate pr-6 text-sm font-medium">{m.model}</div>
                      <div className="mt-0.5 truncate text-xs text-ink-3">Ollama · {formatBytes(m.size_bytes)}</div>
                    </SelectCard>
                  ))}
                </div>
              ) : (
                <Alert tone="warning">
                  No Ollama models downloaded yet.{" "}
                  <Link href="/settings#ollama-models" className="font-medium text-ink underline">
                    Download one in Settings
                  </Link>
                  .
                </Alert>
              )
            ) : models.length > 0 ? (
              <div className="grid gap-2 sm:grid-cols-2">
                {models.map((m) => {
                  const ref = modelRef(m);
                  const picked = multiModel ? modelsChosen.includes(ref) : model === ref;
                  const full = multiModel && !picked && modelsChosen.length >= MAX_VARIANTS;
                  const color = multiModel && picked ? variantColor(modelsChosen.indexOf(ref)) : null;
                  return (
                    <SelectCard
                      key={m.folder}
                      role={multiModel ? "checkbox" : "radio"}
                      selected={picked}
                      onClick={() => (multiModel ? !full && toggleModel(ref) : setModel(ref))}
                    >
                      <div className={`flex items-center gap-2 pr-6 text-sm font-medium ${full ? "text-ink-3" : ""}`}>
                        {color && <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: color }} />}
                        <span className="truncate">{ref.split("/").pop()}</span>
                      </div>
                      <div className="mt-0.5 truncate text-xs text-ink-3">
                        {m.model?.split("/")[0] ?? "local"} · {formatBytes(m.size_bytes)}
                        {multiModel && m.gpu_memory_mb != null && ` · ~${gb(m.gpu_memory_mb)} GPU`}
                      </div>
                    </SelectCard>
                  );
                })}
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
            {multiModel && modelsChosen.length === 0 && models.length > 0 && (
              <p className="mt-3 text-xs text-critical-text">Pick at least one model.</p>
            )}
          </Section>
        )}

        {experiment === "temperature-change" && (
          <Section
            title="Temperatures"
            description={`Every prompt is captured once at each temperature. Pick up to ${MAX_VARIANTS}.`}
          >
            <div className="flex flex-wrap gap-1.5">
              {[...new Set([...TEMPERATURE_PRESETS, ...temperatures])]
                .sort((a, b) => a - b)
                .map((t) => {
                  const on = temperatures.includes(t);
                  const full = !on && temperatures.length >= MAX_VARIANTS;
                  return (
                    <button
                      key={t}
                      type="button"
                      aria-pressed={on}
                      disabled={full}
                      onClick={() => toggleTemperature(t)}
                      className={`h-8 min-w-12 rounded-lg px-2.5 text-sm font-medium tabular-nums transition-colors disabled:cursor-not-allowed ${
                        on ? "bg-accent-strong text-white shadow-sm" : "bg-surface-2 text-ink-2 hover:text-ink disabled:text-ink-3"
                      }`}
                    >
                      {t}
                    </button>
                  );
                })}
            </div>
            <form
              className="mt-4 flex items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                addCustomTemperature();
              }}
            >
              <div className="w-40">
                <Field label="Another value">
                  <input
                    type="number"
                    min={0}
                    max={2}
                    step={0.05}
                    value={customTemperature}
                    onChange={(e) => setCustomTemperature(e.target.value)}
                    placeholder="0 to 2"
                    className={inputClass}
                  />
                </Field>
              </div>
              <button type="submit" disabled={temperatures.length >= MAX_VARIANTS} className={buttonClass("secondary")}>
                Add
              </button>
            </form>
            <p className="mt-3 text-xs text-ink-3">
              0 is greedy decoding: always the most likely token, so repeated captures of a prompt give the same response.
              The other experiments sample at 0.7. Above 1 the text gets more and more random.
            </p>
            {temperatures.length === 0 && <p className="mt-2 text-xs text-critical-text">Pick at least one temperature.</p>}
          </Section>
        )}

        {experiment === "delay" && (
          <Section
            title="Network conditions"
            description="tc netem delays everything the inference server sends, the response stream included, before the capture starts. Every prompt is captured once under each condition."
            action={
              <button
                type="button"
                disabled={conditions.length >= MAX_VARIANTS}
                onClick={() => setConditions((c) => [...c, { delay_ms: 100, jitter_ms: 10, distribution: "normal" }])}
                className={buttonClass("secondary", "sm")}
              >
                Add condition
              </button>
            }
          >
            <div className="space-y-2">
              <div className="grid grid-cols-[1.25rem_7rem_7rem_9rem_1fr_2rem] gap-3 px-1 text-xs font-medium text-ink-3">
                <span />
                <span>Delay (ms)</span>
                <span>Jitter (ms)</span>
                <span>Jitter shape</span>
                <span />
                <span />
              </div>
              {conditions.map((c, i) => {
                const problem = conditionProblem(conditions, i);
                return (
                  <div
                    key={i}
                    className="grid grid-cols-[1.25rem_7rem_7rem_9rem_1fr_2rem] items-center gap-3 rounded-xl border border-hairline px-1 py-2"
                  >
                    <span className="flex justify-center">
                      <span className="h-2 w-2 rounded-full" style={{ background: variantColor(i) }} />
                    </span>
                    <input
                      type="number"
                      min={0}
                      max={10000}
                      value={c.delay_ms}
                      onChange={(e) => updateCondition(i, { delay_ms: Math.min(10000, Math.max(0, Math.round(Number(e.target.value) || 0))) })}
                      className={inputClass}
                      aria-label={`Delay of condition ${i + 1}, in milliseconds`}
                    />
                    <input
                      type="number"
                      min={0}
                      max={10000}
                      value={c.jitter_ms}
                      onChange={(e) => updateCondition(i, { jitter_ms: Math.min(10000, Math.max(0, Math.round(Number(e.target.value) || 0))) })}
                      className={inputClass}
                      aria-label={`Jitter of condition ${i + 1}, in milliseconds`}
                    />
                    <select
                      value={c.distribution}
                      disabled={!c.jitter_ms}
                      onChange={(e) => updateCondition(i, { distribution: e.target.value as NetworkCondition["distribution"] })}
                      className={`${inputClass} disabled:text-ink-3`}
                      aria-label={`Jitter distribution of condition ${i + 1}`}
                    >
                      {DISTRIBUTIONS.map((d) => (
                        <option key={d} value={d}>
                          {d}
                        </option>
                      ))}
                    </select>
                    <span className={`truncate text-sm ${problem ? "text-critical-text" : "text-ink-2"}`}>
                      {problem ?? conditionLabel(c)}
                    </span>
                    <button
                      type="button"
                      onClick={() => setConditions((cur) => cur.filter((_, j) => j !== i))}
                      disabled={conditions.length === 1}
                      className="flex h-8 w-8 items-center justify-center rounded-lg text-ink-3 hover:bg-surface-2 hover:text-critical-text disabled:invisible"
                      aria-label={`Remove condition ${i + 1}`}
                      title="Remove"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                );
              })}
            </div>
            <p className="mt-3 text-xs text-ink-3">
              Keep a condition with no delay to compare against. Jitter varies each packet&apos;s delay around the set
              value, following the chosen distribution. The host kernel needs the sch_netem module (
              <code className="text-ink-2">sudo modprobe sch_netem</code>).
            </p>
          </Section>
        )}

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
                  The {severalModels ? "largest model" : "model"} needs about {gb(needMb)}, more than GPU {tooSmall.map((g) => g.index).join(", ")} can hold on
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
                  ? ` The captures are divided between them: ${total} capture${total === 1 ? "" : "s"} over ${workerCount} workers is ${shareText} each, so they finish up to ${workerCount}× sooner.`
                  : gpuMode === "auto" && system.gpus.length > 1
                    ? ` With ${system.gpus.length} workers, each GPU runs its own copy and the prompts are divided between them.`
                    : " Add workers to finish sooner."}
              </p>
              {onGpu && perGpuNeed != null && (
                <p>
                  Needs about <span className="font-medium text-ink-2">{gb(perGpuNeed)}</span> of GPU memory
                  {gpuMode === "auto" ? " per worker" : " on each selected GPU"}
                  {severalModels && ", enough for the largest model"}
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

        {/* A Custom Experiment's editor stays mounted behind the library, so an edit it is still saving isn't lost */}
        {(writesPrompts || byScenario) && (
          <div className={ownPrompts ? undefined : "hidden"}>
            <CustomPromptsEditor experiment={experiment} lead={promptSourceToggle} onChange={setCustomPrompts} />
          </div>
        )}
        {!ownPrompts && (
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
            {promptSourceToggle}
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
        )}

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
          {!setsTemperature && defaultTemperature != null && (
            <p className="mt-4 text-xs text-ink-3">
              The model samples at temperature <span className="font-medium text-ink-2">{defaultTemperature}</span>
              {defaultTemperature === 0 && " (greedy decoding)"}, the default set in{" "}
              <Link href="/settings" className="font-medium text-ink-2 underline">
                Settings
              </Link>
              .
            </p>
          )}
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
            {info?.variable && (
              <div className="mt-1 text-xs text-ink-3 tabular-nums">
                {promptCount} prompt{promptCount === 1 ? "" : "s"}
                {repeat > 1 && ` × ${repeat}`} × {variantCount} {variantCount === 1 ? info.variable.one : info.variable.many}
              </div>
            )}
          </div>
          <dl className="divide-y divide-[var(--hairline)] px-5 text-sm">
            {[
              [multiModel || severalModels ? "Models" : "Model", modelText],
              ...(onOllama ? [["Provider", "Ollama"]] : []),
              ...(byScenario ? [["Scenarios", `${scenarios.length}`]] : []),
              ...(experiment === "temperature-change"
                ? [["Temperatures", temperatures.length ? temperatures.join(", ") : "—"]]
                : experiment === "delay"
                  ? [["Conditions", `${conditions.length}`]]
                  : []),
              ["Hardware", hardware],
              ["Workers", workerCount > 1 ? `${workerCount} · ${shareText} captures each` : "1"],
              ...(onGpu && needMb != null ? [["GPU memory", `~${gb(needMb * workerCount)}`]] : []),
              [
                "Prompts",
                ownPrompts
                  ? `${promptCount} written here`
                  : `${selected.size} from ${selectedCategories} categor${selectedCategories === 1 ? "y" : "ies"}`,
              ],
              ["Repeat", repeat > 1 ? `× ${repeat}` : "Once"],
              ...(!setsTemperature && defaultTemperature != null ? [["Temperature", `${defaultTemperature}`]] : []),
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
                placeholder={
                  byScenario
                    ? "e.g. 7B models under delay"
                    : multiModel
                      ? "e.g. 7B models"
                      : model
                        ? `${shortName(onOllama && ollamaModel ? ollamaModel : model)} ${sweepsTemperature ? "temperature sweep" : experiment === "delay" ? "under delay" : ownPrompts ? "crafted prompts" : "baseline"}`
                        : "e.g. Qwen baseline"
                }
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
