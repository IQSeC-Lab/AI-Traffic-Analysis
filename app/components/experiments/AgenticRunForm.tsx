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
import { TasksEditor } from "./TasksEditor";

const gb = (mb: number) => `${(mb / 1024).toFixed(1)} GB`;

/** New run of an agentic experiment: tasks for MARBLE's agents, each captured once per topology. */
export function AgenticRunForm({ experiment }: { experiment: string }) {
  const router = useRouter();
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [catalog, setCatalog] = useState<TaskCatalog | null>(null);
  const [models, setModels] = useState<OllamaModel[]>([]);
  const [activeRuns, setActiveRuns] = useState<Run[]>([]);

  const [model, setModel] = useState("");
  // Good Agent Bad Agent: the models the agents take in turn, and the team
  const [teamModels, setTeamModels] = useState<string[]>([]);
  const [good, setGood] = useState(2);
  const [bad, setBad] = useState(1);
  const [control, setControl] = useState(true);
  const [goodPrompt, setGoodPrompt] = useState("");
  const [badPrompt, setBadPrompt] = useState("");
  const [topologies, setTopologies] = useState<string[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [perCategory, setPerCategory] = useState(1);
  const [repeat, setRepeat] = useState(1);
  const [gpuMode, setGpuMode] = useState<"auto" | "manual" | "cpu">("auto");
  const [gpus, setGpus] = useState<number[]>([]);
  const [workers, setWorkers] = useState(1);
  const [name, setName] = useState("");
  const [starting, setStarting] = useState(false);
  const [savingTasks, setSavingTasks] = useState(false); // a run reads the saved tasks (TasksEditor)
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
        if (tasks.team) {
          const first = pulled.find((m) => m.model === tasks.default_model) ?? pulled[0];
          setTeamModels(first ? [first.model] : []);
          setGood(tasks.team.good);
          setBad(tasks.team.bad);
          setGoodPrompt(tasks.team.good_prompt);
          setBadPrompt(tasks.team.bad_prompt);
        }
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
    return error ? <Alert>{error}</Alert> : <Loading label="Reading the tasks…" />;
  }

  const toggle = (list: string[], value: string) => (list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);
  // A category whose tasks were all removed (TasksEditor) stays picked but can't run
  const chosen = catalog.categories.filter((c) => categories.includes(c.slug) && c.tasks.length > 0);
  // Every chosen category runs the same task numbers, so the smallest one sets how many there can be
  const maxTasks = chosen.length ? Math.min(...chosen.map((c) => c.tasks.length)) : catalog.dataset_tasks;
  const taskCount = Math.max(1, Math.min(perCategory, maxTasks));
  const tasks = chosen.length ? chosen[0].tasks.slice(0, taskCount) : [];
  // In the catalog's order, which is the order the run compares them in
  const picked = catalog.topologies.filter((t) => topologies.includes(t.key));
  const team = catalog.team;
  const size = good + bad;
  // What every task is captured as, in the run's order (good_bad_agents.variants): with several
  // models each takes its turn in the bad seats, then the control
  const lineups = team
    ? [
        ...teamModels.map((_, r) =>
          bad === 0
            ? teamModels.length > 1 ? `Lineup ${r + 1}` : "Nobody bad"
            : teamModels.length === 1
              ? `${bad} bad agent${bad > 1 ? "s" : ""}`
              : `${[...new Set(Array.from({ length: bad }, (_, i) => teamModels[(i + r) % teamModels.length]))].join(", ")} bad`,
        ),
        ...(control && bad > 0 && teamModels.length > 0 ? ["Nobody bad"] : []),
      ]
    : [];
  const compared = team ? lineups.length : picked.length;
  const total = chosen.length * taskCount * Math.max(1, repeat) * compared;
  const teamProblem = !team
    ? null
    : teamModels.length === 0
      ? "Pick at least one model."
      : size > team.max
        ? `A team has up to ${team.max} agents.`
        : teamModels.length > size
          ? `A team of ${size} agents calls at most ${size} models.`
          : teamModels.length > team.max_models
            ? `Pick up to ${team.max_models} models.`
            : !goodPrompt.trim() || !badPrompt.trim()
              ? "Write both starting prompts."
              : null;

  const onGpu = gpuMode !== "cpu" && system.gpus.length > 0;
  const maxWorkers = catalog.max_workers ?? 16;
  const workerCount = Math.max(1, Math.min(workers, total || 1, maxWorkers));
  // Every model of the team is loaded at once
  const teamMb = teamModels.map((t) => models.find((m) => m.model === t)?.gpu_memory_mb ?? null);
  const needMb = team
    ? teamMb.length && teamMb.every((mb) => mb != null) ? teamMb.reduce((a: number, b) => a + (b ?? 0), 0) : null
    : (models.find((m) => m.model === model)?.gpu_memory_mb ?? null);
  const hardware = !onGpu ? "CPU" : gpuMode === "auto" ? "Auto GPU" : gpus.length ? `GPU ${gpus.join(", ")}` : "—";
  const canStart =
    catalog.available &&
    system.docker.available &&
    (team ? teamProblem == null : model !== "" && picked.length > 0) &&
    chosen.length > 0 &&
    !starting &&
    !savingTasks &&
    !(onGpu && gpuMode === "manual" && gpus.length === 0);

  async function start() {
    setStarting(true);
    setError(null);
    const config: Partial<RunConfig> = {
      ...(team
        ? { models: teamModels, good, bad, control, good_prompt: goodPrompt.trim(), bad_prompt: badPrompt.trim() }
        : { model }),
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
        {catalog.notice && <Alert tone="info">{catalog.notice}</Alert>}

        <Section
          title={team ? "Models" : "Model"}
          description={
            team
              ? "Pick one and every agent calls it. Pick several and the agents take them in turn: every task is then captured once per lineup, each model taking its turn as the bad one."
              : "Ollama models downloaded on this machine. Every agent calls the same one."
          }
          action={
            <ButtonLink href="/settings#ollama-models" variant="secondary" size="sm">
              Download more
            </ButtonLink>
          }
        >
          {models.length > 0 ? (
            <div className="grid gap-2 sm:grid-cols-2">
              {models.map((m) => (
                <SelectCard
                  key={m.model}
                  role={team ? "checkbox" : "radio"}
                  selected={team ? teamModels.includes(m.model) : model === m.model}
                  onClick={() => (team ? setTeamModels((cur) => toggle(cur, m.model)) : setModel(m.model))}
                >
                  <div className="flex items-center gap-2 truncate pr-6 text-sm font-medium">
                    {team && teamModels.includes(m.model) && teamModels.length > 1 && (
                      <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: variantColor(teamModels.indexOf(m.model)) }} />
                    )}
                    {m.model}
                  </div>
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

        {team && (
          <Section
            title="Team"
            description="Good and bad agents differ only in the prompt they start with, which no other agent sees. Which agents are bad is drawn again for every task and repetition."
          >
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Good agents" hint="Working for the team.">
                <input
                  type="number"
                  min={1}
                  max={team.max - bad}
                  value={good}
                  onChange={(e) => setGood(Math.max(1, Math.min(team.max - bad, Number(e.target.value) || 1)))}
                  className={inputClass}
                />
              </Field>
              <Field label="Bad agents" hint="Secretly working against it. 0 runs the team with nobody bad.">
                <input
                  type="number"
                  min={0}
                  max={team.max - good}
                  value={bad}
                  onChange={(e) => setBad(Math.max(0, Math.min(team.max - good, Number(e.target.value) || 0)))}
                  className={inputClass}
                />
              </Field>
            </div>
            <div className="mt-4">
              <SelectCard role="checkbox" selected={control && bad > 0} onClick={() => setControl((on) => !on)}>
                <div className="pr-6 text-sm font-medium">Control</div>
                <div className="mt-0.5 text-xs text-ink-3">
                  {bad > 0 ? "Also capture every task with every agent good, the same agents and models." : "Nobody is bad, so every capture is a control."}
                </div>
              </SelectCard>
            </div>
            {lineups.length > 0 && (
              <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-ink-2">
                <span className="text-ink-3">Every task is captured as</span>
                {lineups.map((label, i) => (
                  <span key={i} className="flex items-center gap-1.5">
                    <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: variantColor(i) }} />
                    {label}
                  </span>
                ))}
              </div>
            )}
            <div className="mt-5 grid gap-4 border-t border-hairline pt-5">
              <Field label="Good agent's prompt" hint="Added after the agent's role in the task.">
                <textarea
                  value={goodPrompt}
                  maxLength={team.prompt_max}
                  rows={2}
                  onChange={(e) => setGoodPrompt(e.target.value)}
                  className={`${inputClass} h-auto resize-y py-2 leading-relaxed`}
                />
              </Field>
              <Field label="Bad agent's prompt" hint="Added after the agent's role in the task. Every bad agent gets the same one.">
                <textarea
                  value={badPrompt}
                  maxLength={team.prompt_max}
                  rows={3}
                  onChange={(e) => setBadPrompt(e.target.value)}
                  className={`${inputClass} h-auto resize-y py-2 leading-relaxed`}
                />
              </Field>
            </div>
            {teamProblem && <p className="mt-3 text-xs text-critical-text">{teamProblem}</p>}
          </Section>
        )}

        {!team && (
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
        )}

        <Section
          title="Tasks"
          description={catalog.about}
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
                  <div className="mt-0.5 text-xs text-ink-3">{c.disabled ?? (catalog.editable ? "No tasks. Add some under Edit tasks." : "No task configs found.")}</div>
                </div>
              ) : (
                <SelectCard key={c.slug} role="checkbox" selected={on} onClick={() => setCategories((cur) => toggle(cur, c.slug))}>
                  <div className="pr-6 text-sm font-medium">{c.label}</div>
                  <div className="mt-0.5 text-xs text-ink-3 tabular-nums">
                    {c.about ? `${c.about} · ` : ""}
                    {c.tasks.length} task{c.tasks.length === 1 ? "" : "s"}
                    {c.edited && " · edited"}
                  </div>
                </SelectCard>
              );
            })}
          </div>
          {chosen.length === 0 && <p className="mt-3 text-xs text-critical-text">Pick at least one category.</p>}
          <div className="mt-5 grid gap-4 border-t border-hairline pt-5 sm:grid-cols-2">
            <Field
              label="Tasks per category"
              hint={
                catalog.from_dataset
                  ? `Tasks 1 to ${taskCount} of every chosen category. The dataset uses the first ${catalog.dataset_tasks}; these categories have up to ${maxTasks}.`
                  : `Tasks 1 to ${taskCount} of every chosen category. ${chosen.length > 1 ? `The smallest of them has ${maxTasks}.` : `It has ${maxTasks}.`}`
              }
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

        {catalog.editable && <TasksEditor experiment={experiment} catalog={catalog} onChange={setCatalog} onPending={setSavingTasks} />}

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
                max={maxWorkers}
                value={Math.min(workers, maxWorkers)}
                disabled={maxWorkers === 1}
                onChange={(e) => setWorkers(Math.min(maxWorkers, Math.max(1, Number(e.target.value) || 1)))}
                className={inputClass}
              />
            </Field>
            <p className="text-xs text-ink-3 sm:pt-7">
              {maxWorkers === 1
                ? "This experiment runs with one worker, so that the sites get one request at a time."
                : "Each worker has its own Ollama, network and capture, and the tasks are divided between them. Workers that share a GPU slow each other down, which changes the timings you capture."}
              {onGpu && needMb != null && ` Ollama needs about ${gb(needMb)} of GPU memory per worker for ${team && teamModels.length > 1 ? "these models" : "this model"}.`}
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
              {repeat > 1 && ` × ${repeat}`} × {compared}{" "}
              {team ? (compared === 1 ? "lineup" : "lineups") : compared === 1 ? "topology" : "topologies"}
            </div>
          </div>
          <dl className="divide-y divide-[var(--hairline)] px-5 text-sm">
            {[
              ...(team
                ? [
                    ["Models", teamModels.join(", ") || "—"],
                    ["Team", `${good} good, ${bad} bad`],
                    ["Lineups", `${lineups.length}`],
                  ]
                : [
                    ["Model", model || "—"],
                    ["Topologies", picked.map((t) => t.label).join(", ") || "—"],
                  ]),
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
              <input value={name} maxLength={60} onChange={(e) => setName(e.target.value)} placeholder={`e.g. Graph and star, ${catalog.dataset_tasks} tasks`} className={inputClass} />
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
