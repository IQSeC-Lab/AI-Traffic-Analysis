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
};

export type Prompt = {
  number: number;
  category: string;
  text: string;
  builtin: boolean;
  created_at?: string;
};

export type PromptCategory = { name: string; count: number; builtin: boolean };

export type PromptLibrary = { prompts: Prompt[]; categories: PromptCategory[] };

export type RunConfig = {
  model: string;
  prompts: number[] | null;
  repeat: number | null;
  gpus: number[] | "auto"; // "auto" = the GPU with the most free memory; [] = CPU
  max_tokens: number;
  workers?: number; // model instances sharing the prompts, each with its own capture
  name?: string | null; // only sent when starting a run
};

export type RunWorker = {
  gpus: number[];
  current: { prompt: number; iteration: number | null; index: number } | null;
  step: string | null;
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
  experiment: string;
  status: RunStatus;
  step: string | null;
  current: { prompt: number; iteration: number | null; index: number } | null;
  config: RunConfig;
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
    network: string | null;
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

export type Analytics = {
  runs: {
    id: string;
    model: string;
    status: RunStatus;
    created_at: string;
    summary: RunSummaryStats;
    by_category: CategoryStats[];
  }[];
  gap_hist: Histogram;
  size_hist: Histogram;
};

export type Capture = {
  index: number;
  prompt: number;
  iteration: number | null;
  category: string | null;
  metrics: Partial<CaptureMetrics>;
  error: string | null;
};

export type CaptureDetail = {
  index: number;
  prompt: number;
  iteration: number | null;
  category: string | null;
  metrics: Partial<CaptureMetrics>;
  prompt_text: string;
  response: string | null;
  stream_timeline: [number, number][];
  events: [number, number, string][];
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
