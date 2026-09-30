import { Layers, Radar, Syringe, Thermometer, Timer, type LucideIcon } from "lucide-react";

export type ExperimentInfo = {
  slug: string;
  name: string;
  summary: string;
  description: string;
  icon: LucideIcon;
  available: boolean;
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
    description: "How sampling temperature changes inter-token timing, packet sizes and stream duration.",
    icon: Thermometer,
    available: false,
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
    description: "Whether traffic fingerprints generalize across model sizes and architectures.",
    icon: Layers,
    available: false,
  },
  {
    slug: "delay",
    name: "Delay",
    summary: "Network delay & jitter",
    description: "Fingerprint robustness under injected network delay and jitter.",
    icon: Timer,
    available: false,
  },
];

export const experimentHref = (slug: string) => `/experiments/${slug}`;
export const runHref = (id: string) => `/experiments/data-collector/runs/${id}`;
