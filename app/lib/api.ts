// Typed client for the FastAPI backend (api/). Requests go to /api/* and
// Next.js proxies them to FastAPI (see next.config.ts).

export type Gpu = {
  index: number;
  name: string;
  memory_total_mb: number | null;
  memory_used_mb: number | null;
  utilization_pct: number | null;
};

export type SystemInfo = {
  gpus: Gpu[];
  docker: { available: boolean; version: string | null; error: string | null };
};

export type LocalModel = {
  folder: string;
  model: string | null;
  size_bytes: number;
  complete: boolean;
  downloading: boolean;
  gpu_memory_mb?: number | null; // rough estimate to load it and generate
};

/** What the experiment API accepts as `model`: the repo id when known, else the folder name. */
export const modelRef = (m: LocalModel) => m.model ?? m.folder;

export type Download = {
  id: string;
  model: string;
  revision: string | null;
  status: "queued" | "preparing" | "downloading" | "completed" | "failed";
  error: string | null;
  downloaded_bytes: number | null;
  total_bytes: number | null;
  target: string;
  created_at: string;
  finished_at: string | null;
};

export type ModelsResponse = {
  models_dir: string;
  models: LocalModel[];
  downloads: Download[];
};

/** A model pulled from the Ollama library: the agentic experiments, and the Data Collector on Ollama. */
export type OllamaModel = {
  model: string; // as Ollama names it, tag included: llama3.2:3b
  size_bytes: number;
  complete: boolean;
  gpu_memory_mb: number | null;
  downloading: boolean;
};

export type OllamaModelsResponse = {
  models_dir: string;
  models: OllamaModel[];
  downloads: Download[];
};

/** What a Topology Transfer run can use, from the MARBLE code on the server. */
export type TaskCatalog = {
  available: boolean; // false: the MARBLE code isn't where the API looks for it
  problem: string | null;
  marble_dir: string;
  repo: string;
  default_model: string;
  dataset_tasks: number; // the published dataset uses tasks 1 to this of each category
  topologies: { key: string; label: string }[];
  categories: { slug: string; label: string; disabled: string | null; tasks: number[] }[];
};

export type TokenStatus = {
  set: boolean;
  source: "saved" | "env" | null;
  hint: string | null;
  username: string | null;
};

export type Settings = {
  hf_token: TokenStatus;
  models_dir: string;
  results_dir: string; // where new runs are saved
  results_default: string;
  results_dirs: string[]; // every folder runs were saved in (all still listed)
  default_temperature: number; // sampling temperature of new runs that don't set their own
  original_temperature: number; // what the original scripts sample at (0.7)
};

export type Prompt = {
  number: number;
  category: string;
  text: string;
  builtin: boolean;
  created_at?: string;
};

export type PromptCategory = { name: string; count: number; builtin: boolean };

/** An experiment's own prompts (Custom Prompts, the Custom Experiment), kept apart from the prompt library. */
export type CustomPrompts = {
  prompts: string[]; // the saved set (the crafted prompts until something is saved)
  crafted: string[]; // the 10 prompts of 4-Crafted-Prompts
  max_prompts: number;
  max_chars: number;
};

export type PromptLibrary = { prompts: Prompt[]; categories: PromptCategory[] };

export type NetworkCondition = {
  delay_ms: number;
  jitter_ms: number; // needs a delay
  distribution: "normal" | "pareto" | "paretonormal"; // shape of the jitter
};

export const DISTRIBUTIONS: NetworkCondition["distribution"][] = ["normal", "pareto", "paretonormal"];

/** One scenario of a Custom Experiment run. */
export type Scenario = {
  model: string;
  temperature: number | null; // null: the default from Settings
  network: NetworkCondition; // no delay: left as it is
  label: string | null; // null: named by what sets it apart from the others
};

export type RunConfig = {
  model?: string; // every experiment but Scalability and the Custom Experiment
  provider?: "transformers" | "ollama"; // Data Collector: the app's own server, or Ollama
  topologies?: string[]; // Topology Transfer
  categories?: string[]; // Topology Transfer: MARBLE task categories
  tasks?: number[]; // Topology Transfer: task numbers run in every category
  models?: string[]; // Scalability: the models compared
  scenarios?: Scenario[]; // Custom Experiment
  prompt_source?: "library" | "written"; // Custom Experiment: prompt library numbers, or prompts written for it
  temperatures?: number[]; // Temperature Change: 0 is greedy decoding
  conditions?: NetworkCondition[]; // Delay
  prompt_texts?: string[]; // written prompts: the prompts themselves (only sent when starting a run)
  prompts: number[] | null; // prompt library numbers, null = all. Not used by Custom Prompts
  repeat: number | null;
  gpus: number[] | "auto"; // "auto" = spread over the GPUs with room; [] = CPU
  split_model?: boolean; // chosen GPUs: split every worker's model across all of them, instead of one GPU each
  max_tokens: number;
  workers?: number; // model instances dividing the prompts, each with its own containers, network and capture
  name?: string | null; // only sent when starting a run
};

/** The capture a worker is on. `variant` is a Variant key (runs before variants have none). */
export type CurrentCapture = { prompt: number; iteration: number | null; index: number; variant?: string };

export type RunWorker = {
  gpus: number[];
  network?: string;
  done?: number; // captures finished, of its `total` share of the prompts
  total?: number;
  current: CurrentCapture | null;
  step: string | null;
};

/** One setting a run compares: a temperature, a model, a network condition, a scenario. The Data Collector has one. */
export type Variant = {
  key: string; // its captures are <key>-pNN
  label: string;
  model: string;
  temperature: number | null; // what it sampled at. null on runs from before it was recorded: 0.7
  network: NetworkCondition | null; // null: no delay added
  columns: Record<string, string | number | null>;
  done?: number; // captures finished, of `total`
  total?: number;
};

export type RunStatus =
  | "queued"
  | "pending"
  | "running"
  | "cancelling"
  | "cleaning_up"
  | "completed"
  | "failed"
  | "cancelled"
  | "interrupted";

export type Run = {
  id: string;
  number?: number; // #1, #2, ... never reused
  name?: string | null;
  experiment: string; // the experiment's slug
  status: RunStatus;
  step: string | null;
  current: CurrentCapture | null;
  config: RunConfig;
  models: string[];
  variants: Variant[];
  assigned_gpus?: number[] | null; // where the scheduler started it ([] = CPU)
  workers?: RunWorker[];
  gpu_memory_mb?: number | null;
  queue?: { position: number | null; reason: string | null } | null;
  started_at?: string | null;
  progress: { completed: number; total: number };
  prompt_count?: number; // missing on runs saved before custom prompts existed
  outputs: { pcaps: number; pcap_bytes: number };
  created_at: string;
  finished_at: string | null;
  error: string | null;
  output_dir: string;
  cleanup: {
    containers: string[];
    networks?: string[];
    network?: string | null; // runs from before each worker had its own network
    images: string[];
    errors: string[];
  } | null;
};

export type RunLogs = { lines: string[]; next: number };

// ── Analytics ────────────────────────────────────────────────────────────────

export type CaptureMetrics = {
  packets: number;
  bytes: number;
  capture_s: number;
  stream_packets: number;
  stream_bytes: number;
  stream_s: number;
  median_packet_bytes: number | null;
  median_gap_ms: number | null;
  events: number | null;
  ttft_ms: number | null;
  duration_s: number | null;
  events_per_s: number | null;
  response_chars: number | null;
};

export type RunSummaryStats = {
  captures: number;
  median_ttft_ms: number | null;
  median_events_per_s: number | null;
  median_duration_s: number | null;
  median_gap_ms: number | null;
  median_stream_packets: number | null;
  median_packet_bytes: number | null;
  median_response_chars: number | null;
  total_bytes: number;
};

export type CategoryStats = RunSummaryStats & { category: string };

export type Histogram = { edges: number[]; series: Record<string, number[]>; outside?: Record<string, number> };

/** Summaries and distributions per group: a run's variants, or runs compared. Histogram series are keyed by group key. */
export type Analytics = {
  summary?: RunSummaryStats; // over all the run's captures (a single run's analytics)
  groups: { key: string; label: string; summary: RunSummaryStats; by_category: CategoryStats[] }[];
  gap_hist: Histogram;
  size_hist: Histogram;
};

export type Capture = {
  key: string; // file stem, how the API addresses the capture
  variant: string;
  index: number;
  prompt: number;
  iteration: number | null;
  category: string | null;
  worker?: number | null; // which worker captured it (1, 2, ...), and on which GPUs
  gpus?: number[] | null;
  metrics: Partial<CaptureMetrics>;
  error: string | null;
};

export type CaptureDetail = {
  key: string;
  variant: string;
  index: number;
  prompt: number;
  iteration: number | null;
  category: string | null;
  worker?: number | null;
  gpus?: number[] | null;
  metrics: Partial<CaptureMetrics>;
  prompt_text: string;
  response: string | null;
  stream_timeline: [number, number][];
  events: [number, number, string][];
  downsampled: boolean;
};

// ── Agentic runs: a capture is a MARBLE task, measured over every connection of its agents ──

export type AgenticMetrics = {
  packets: number; // everything captured
  bytes: number;
  capture_s: number;
  // The measurements of the dataset's analysis, over the encrypted application packets
  total_packets: number | null;
  total_bytes: number | null;
  task_duration: number | null;
  packets_per_second: number | null;
  total_bursts: number | null;
  idle_time_fraction: number | null;
  incoming_packets: number;
  median_packet_bytes: number | null;
  median_gap_ms: number | null;
  calls: number | null; // LLM calls the agents made
  agents: number | null;
  run_s: number | null; // how long MARBLE ran
};

/** Medians over the completed tasks of a group. */
export type AgenticStats = {
  captures: number; // completed tasks
  failed: number;
  median_total_packets: number | null;
  median_total_bytes: number | null;
  median_task_duration: number | null;
  median_packets_per_second: number | null;
  median_total_bursts: number | null;
  median_idle_time_fraction: number | null;
  median_calls: number | null;
  median_agents: number | null;
  median_gap_ms: number | null;
  median_packet_bytes: number | null;
  total_bytes: number;
};

/** Per topology: task categories (rows) against traffic measurements (columns), standardized across the categories. */
export type TrafficHeatmap = {
  metrics: { key: string; label: string }[];
  topologies: {
    key: string;
    label: string;
    categories: string[];
    tasks: number[]; // tasks behind each category's row
    z: (number | null)[][];
    medians: (number | null)[][];
  }[];
};

export type AgenticAnalytics = {
  summary: AgenticStats;
  groups: { key: string; label: string; summary: AgenticStats; by_category: (AgenticStats & { category: string })[] }[];
  gap_hist: Histogram;
  size_hist: Histogram;
  heatmap: TrafficHeatmap;
};

export type TaskStatus = "running" | "completed" | "failed";

export type AgenticCapture = {
  key: string;
  variant: string;
  index: number;
  prompt: number; // the task's number in the run
  iteration: number | null;
  category: string | null;
  task_id: number | null; // its number in its MARBLE category
  status: TaskStatus | null;
  worker?: number | null;
  gpus?: number[] | null;
  metrics: Partial<AgenticMetrics>;
  error: string | null;
};

export type AgenticCaptureDetail = AgenticCapture & {
  task_text: string;
  timeline: [number, number, number][]; // seconds, payload bytes, 1 to the model server / -1 from it
  calls: [string, number, number][]; // agent, start and end in seconds
  agents: { agent: string; calls: number; packets: number; bytes: number }[];
  unattributed_packets: number;
  log_tail: string;
  downsampled: boolean;
};

export const ACTIVE_RUN_STATUSES: RunStatus[] = ["queued", "pending", "running", "cancelling", "cleaning_up"];
export const isActive = (run: Pick<Run, "status">) => ACTIVE_RUN_STATUSES.includes(run.status);
export const ACTIVE_DOWNLOAD_STATUSES: Download["status"][] = ["queued", "preparing", "downloading"];

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = body?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: { msg: string }) => d.msg).join("; ")
          : res.status >= 500
            ? `The API server didn't respond (HTTP ${res.status}). Is it running? Start it with npm run dev.`
            : `Request failed (${res.status})`;
    throw new ApiError(message, res.status);
  }
  return body as T;
}
