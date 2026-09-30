import { Layers, Radar, Syringe, Thermometer, Timer, type LucideIcon } from "lucide-react";

export type ExperimentInfo = {
  slug: string;
  name: string;
  summary: string;
  description: string;
  icon: LucideIcon;
  available: boolean;
  /** What a run compares (its variants), in lowercase: "temperature". None for the Data Collector. */
  variable?: { one: string; many: string };
  /** New run form defaults, as in the original experiment's scripts. */
  defaults?: { category?: string; repeat?: number };
};

// The experiments from the repo (2-6), added to the app one at a time.
export const EXPERIMENTS: ExperimentInfo[] = [
  {
    slug: "data-collector",
    name: "Data Collector",
    summary: "Baseline traffic capture",
    description:
      "Streams prompts from the library (60 built in, plus your own) through a fresh inference container each time and captures every packet.",
    icon: Radar,
    available: true,
  },
  {
    slug: "temperature-change",
    name: "Temperature Change",
    summary: "Sampling temperature sweep",
    description:
      "How sampling temperature changes inter-token timing, packet sizes and stream duration. A run captures every prompt at each temperature you pick.",
    icon: Thermometer,
    available: true,
    variable: { one: "temperature", many: "temperatures" },
  },
  {
    slug: "crafted-prompts",
    name: "Crafted Prompts",
    summary: "Prompt-injection traffic",
    description: "Traffic from adversarially crafted prompts, following the LLMmap methodology.",
    icon: Syringe,
    available: false,
  },
  {
    slug: "scalability",
    name: "Scalability",
    summary: "Across models, 3B to 14B",
    description:
      "Whether traffic fingerprints generalize across model sizes and architectures. A run sends the same prompts to each model you pick.",
    icon: Layers,
    available: true,
    variable: { one: "model", many: "models" },
    // 5-Scalability: the 10 code generation prompts, 10 times each (r1.py)
    defaults: { category: "Code Generation", repeat: 10 },
  },
  {
    slug: "delay",
    name: "Delay",
    summary: "Network delay & jitter",
    description:
      "Fingerprint robustness under injected network delay and jitter. A run captures every prompt under each network condition you set.",
    icon: Timer,
    available: true,
    variable: { one: "network condition", many: "network conditions" },
    // 6-Delay: the 10 logical reasoning puzzles, 10 times each (r1.py)
    defaults: { category: "Logical Reasoning & Puzzles", repeat: 10 },
  },
];

/** An experiment that can be opened in the app, by slug. */
export const availableExperiment = (slug: string) => EXPERIMENTS.find((e) => e.slug === slug && e.available);

export const experimentName = (slug: string) => EXPERIMENTS.find((e) => e.slug === slug)?.name ?? slug;

export const experimentHref = (slug: string) => `/experiments/${slug}`;
export const runHref = (run: { experiment: string; id: string }) => `/experiments/${run.experiment}/runs/${run.id}`;
