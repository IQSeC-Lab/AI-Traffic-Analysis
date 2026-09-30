export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  return `${value.toFixed(unit === 0 || value >= 100 ? 0 : 1)} ${units[unit]}`;
}

/** Milliseconds, scaled to µs / ms / s. */
export function formatMs(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1) return `${+(ms * 1000).toPrecision(3)} µs`;
  if (ms < 1000) return `${+ms.toPrecision(3)} ms`;
  return `${+(ms / 1000).toPrecision(3)} s`;
}

export function formatDuration(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s % 60}s`;
  return `${s}s`;
}

export function formatNumber(value: number | null | undefined, digits = 1): string {
  if (value == null) return "—";
  if (Math.abs(value) >= 1e6) return `${+(value / 1e6).toFixed(digits)}M`;
  if (Math.abs(value) >= 1e4) return `${+(value / 1e3).toFixed(digits)}K`;
  return Number.isInteger(value) ? value.toLocaleString() : (+value.toFixed(digits)).toLocaleString();
}

export function formatPercent(fraction: number, digits = 1): string {
  return `${(fraction * 100).toFixed(digits)}%`;
}

export function timeAgo(iso: string, now = Date.now()): string {
  const s = Math.round((now - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** Where a run runs: its assigned GPUs once started, otherwise what it asked for. */
/** "Worker 2 · GPU 1" — which worker made a capture, and where it ran. */
export function workerLabel(worker: number, gpus?: number[] | null): string {
  const where = gpus == null ? "" : gpus.length ? ` · GPU ${gpus.join(", ")}` : " · CPU";
  return `Worker ${worker}${where}`;
}

export function hardwareLabel(run: { assigned_gpus?: number[] | null; config: { gpus: number[] | "auto" } }): string {
  const gpus = run.assigned_gpus ?? run.config.gpus;
  if (gpus === "auto") return "Auto GPU";
  return gpus.length ? `GPU ${gpus.join(", ")}` : "CPU";
}
