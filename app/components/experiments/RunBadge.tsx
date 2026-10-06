import type { Run, Variant } from "@/lib/api";
import { EXPERIMENTS } from "@/lib/experiments";

export const modelName = (model: string) => model.split("/").pop() ?? model;

/** What a run is called: its name if it has one, otherwise its model (the first of several, +N). */
export const runTitle = (run: Pick<Run, "name" | "models">) => {
  if (run.name) return run.name;
  const [first = "", ...rest] = run.models;
  return rest.length ? `${modelName(first)} +${rest.length}` : modelName(first);
};

/**
 * The temperature a whole run sampled at. Null when its variants differ: a Temperature Change
 * run, or a Custom Experiment with several. Runs from before it was recorded sampled at 0.7.
 */
export function runTemperature(run: Pick<Run, "experiment" | "variants">): number | null {
  if (run.experiment === "temperature-change") return null;
  const temperatures = new Set(run.variants.map((v) => v.temperature ?? 0.7));
  return temperatures.size === 1 ? [...temperatures][0] : null;
}

/** Chart color of the run's i-th variant (the validated series palette). */
export const variantColor = (i: number) => `var(--series-${(i % 8) + 1})`;

/** How the UI names a variant: the model's short name on Scalability, otherwise its label. */
export const variantLabel = (experiment: string, v: Pick<Variant, "label" | "model">) =>
  experiment === "scalability" ? modelName(v.model) : v.label;

/** What a run compares, in a few words ("3 temperatures: 0.3, 0.7, 0.9"). Null when it compares nothing. */
export function comparesText(run: Pick<Run, "experiment" | "variants">): string | null {
  const variable = EXPERIMENTS.find((e) => e.slug === run.experiment)?.variable;
  if (!variable) return null;
  const n = run.variants.length;
  const noun = n === 1 ? variable.one : variable.many;
  if (run.experiment === "temperature-change") {
    return `${n} ${noun}: ${run.variants.map((v) => v.temperature).join(", ")}`;
  }
  return `${n} ${noun}`;
}

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
