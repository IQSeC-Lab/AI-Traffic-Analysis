import type { Run } from "@/lib/api";

export const modelName = (model: string) => model.split("/").pop() ?? model;

/** What a run is called: its name if it has one, otherwise its model. */
export const runTitle = (run: Pick<Run, "name" | "config">) => run.name || modelName(run.config.model);

/**
 * The run's number (#7) as a colored badge. The color comes from the number,
 * so a run looks the same everywhere it appears.
 */
export function RunBadge({ number, size = "sm" }: { number?: number | null; size?: "sm" | "lg" }) {
  if (!number) return null;
  const color = `var(--series-${((number - 1) % 8) + 1})`;
  const sizes = size === "lg" ? "h-9 min-w-12 rounded-xl px-2.5 text-base" : "h-6 min-w-9 rounded-md px-1.5 text-xs";
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center gap-1.5 font-semibold text-ink tabular-nums ${sizes}`}
      style={{
        background: `color-mix(in oklab, ${color} 16%, var(--surface))`,
        boxShadow: `inset 0 0 0 1px color-mix(in oklab, ${color} 40%, transparent)`,
      }}
      title={`Run #${number}`}
    >
      <span className={`rounded-full ${size === "lg" ? "h-2 w-2" : "h-1.5 w-1.5"}`} style={{ background: color }} />#{number}
    </span>
  );
}
