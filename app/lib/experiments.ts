import {
  ChartBarDecreasing,
  Grid3x3,
  Layers,
  PenLine,
  Radar,
  SlidersHorizontal,
  Thermometer,
  Timer,
  Waypoints,
  type LucideIcon,
} from "lucide-react";

export type ExperimentInfo = {
  slug: string;
  name: string;
  summary: string;
  description: string;
  icon: LucideIcon;
  available: boolean;
  /** What a run compares (its variants), in lowercase: "temperature". None for the Data Collector. */
  variable?: { one: string; many: string };
  /** A run is a list of scenarios, each with its own model, temperature and network condition. */
  scenarios?: boolean;
  /** New run form defaults, as in the original experiment's scripts. */
  defaults?: { category?: string; repeat?: number };
  /** Its prompts are written in the experiment itself instead of chosen from the prompt library. */
  ownPrompts?: boolean;
};

// A run compares at most 8 temperatures, models, network conditions or scenarios: one chart color each.
export const MAX_VARIANTS = 8;

// The experiments from the repo (2-6), then the one the app adds.
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
    slug: "custom-prompts",
    name: "Custom Prompts",
    summary: "Prompts written for the run",
    description:
      "Traffic from prompts you write here, kept apart from the prompt library. It starts with the 10 adversarially crafted prompts that follow the LLMmap methodology.",
    icon: PenLine,
    available: true,
    // 4-Crafted-Prompts: its 10 prompts, 10 times each (r1.py)
    defaults: { repeat: 10 },
    ownPrompts: true,
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
  {
    slug: "custom-experiment",
    name: "Custom Experiment",
    summary: "Your own scenarios",
    description:
      "A run you set up yourself, with every setting the other experiments have. Each scenario has its own model, sampling temperature and network condition, and every prompt is captured once per scenario.",
    icon: SlidersHorizontal,
    available: true,
    variable: { one: "scenario", many: "scenarios" },
    scenarios: true,
  },
];

// The agentic orchestrator experiments (MARBLE, graph and star topologies). Not in the app yet, so they are
// kept out of EXPERIMENTS: they have no runs, forms or pages.
export const ORCHESTRATOR_EXPERIMENTS: ExperimentInfo[] = [
  {
    slug: "traffic-heatmap",
    name: "Traffic Heatmap",
    summary: "Traffic by task category",
    description:
      "Six payload-independent traffic measurements per MARBLE execution, aggregated by task and compared across the ten task categories.",
    icon: Grid3x3,
    available: false,
  },
  {
    slug: "feature-importance",
    name: "Feature Importance",
    summary: "Top 10 Random Forest features",
    description:
      "Which of the 247 traffic features identify a task. Random Forests are trained per topology over five task-grouped folds, and the ten most important features are ranked for graph and star.",
    icon: ChartBarDecreasing,
    available: false,
  },
  {
    slug: "topology-transfer",
    name: "Topology Transfer",
    summary: "Across topologies and visible agents",
    description:
      "Task fingerprinting within one topology and from graph to star, and how accuracy changes with the number of agents whose traffic is observed.",
    icon: Waypoints,
    available: false,
  },
];

/** An experiment that can be opened in the app, by slug. */
export const availableExperiment = (slug: string) => EXPERIMENTS.find((e) => e.slug === slug && e.available);

export const experimentName = (slug: string) => EXPERIMENTS.find((e) => e.slug === slug)?.name ?? slug;

/** Whether a run's prompts were written for it: always in Custom Prompts, by choice in a Custom Experiment. Its results then go prompt by prompt. */
export const hasOwnPrompts = (run: { experiment: string; config: { prompt_source?: string } }) =>
  run.config.prompt_source === "written" || (EXPERIMENTS.find((e) => e.slug === run.experiment)?.ownPrompts ?? false);

export const experimentHref = (slug: string) => `/experiments/${slug}`;
export const runHref = (run: { experiment: string; id: string }) => `/experiments/${run.experiment}/runs/${run.id}`;
