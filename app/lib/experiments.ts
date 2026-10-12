import {
  Database,
  Globe,
  Layers,
  Network,
  PenLine,
  Radar,
  SlidersHorizontal,
  Thermometer,
  Timer,
  Users,
  Waypoints,
  type LucideIcon,
} from "lucide-react";

/** What an agentic experiment captures: who the agents talk to, and what one exchange with it is called. */
export type AgenticInfo = {
  peer: string;
  call: { one: string; many: string };
  failed?: string;
  /** The PCAP also holds traffic the measurements leave out: said under the total. */
  alsoCaptured?: string;
};

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
  /** Agentic AI: a capture is a task worked on by several agents, not one prompt and its response. */
  agentic?: AgenticInfo;
};

// A run compares at most 8 temperatures, models, network conditions or scenarios: one chart color each.
export const MAX_VARIANTS = 8;

// Client to server: the experiments from the repo (2-6), then the one the app adds.
// Agentic AI (`agentic`): several agents working on a task, one experiment per kind of
// communication that is captured: with the LLM, with infrastructure, with outside endpoints, with
// other agents, with people. The coordination topology (graph, star) is an option of each.
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
  // Its address and results folder are still "topology-transfer", the name it started with:
  // runs made under that name stay where they are.
  {
    slug: "topology-transfer",
    name: "Agent to LLM",
    summary: "Agents calling one LLM server",
    description:
      "Several agents work on a MARBLE task, and every call they make to the LLM server is captured. A run can capture each task under more than one coordination topology (graph, star), with the same agents and model, so the topologies can be compared.",
    icon: Network,
    available: true,
    variable: { one: "topology", many: "topologies" },
    agentic: { peer: "model server", call: { one: "LLM call", many: "LLM calls" } },
  },
  {
    slug: "agent-to-infrastructure",
    name: "Agent to Infrastructure",
    summary: "Agents working on a database",
    description:
      "Several agents carry out a request on a PostgreSQL database (look rows up, insert, update or delete them, report over many), and every query they send is captured. The database is a mock online store, created again for every task. A run can capture each task under more than one coordination topology.",
    icon: Database,
    available: true,
    variable: { one: "topology", many: "topologies" },
    agentic: { peer: "database", call: { one: "query", many: "queries" }, failed: "Refused by the database" },
  },
  {
    slug: "agent-to-endpoint",
    name: "Agent to Endpoint",
    summary: "Agents looking things up online",
    description:
      "Several agents answer a request by looking it up on public sites, and every request they send is captured: research papers on arXiv, health topics on MedlinePlus, or security advisories (the National Vulnerability Database with CISA's exploited vulnerabilities, OSV and the vendors' own pages). It is the one experiment whose containers reach the internet. A run can capture each task under more than one coordination topology.",
    icon: Globe,
    available: true,
    variable: { one: "topology", many: "topologies" },
    agentic: {
      peer: "sites",
      call: { one: "request", many: "requests" },
      failed: "Failed",
      alsoCaptured: "Traffic captured includes the agents' calls to the model, which the other figures leave out.",
    },
  },
  // Not in the app yet
  {
    slug: "agent-to-agents",
    name: "Agent to Agents",
    summary: "Messages between agents",
    description: "Agents that run apart from each other and exchange tasks and results over the network.",
    icon: Waypoints,
    available: false,
    agentic: { peer: "other agents", call: { one: "message", many: "messages" } },
  },
  {
    slug: "agent-to-people",
    name: "Agent to People",
    summary: "One agent, several people",
    description: "One agent exchanging messages with several people through a chat service.",
    icon: Users,
    available: false,
    agentic: { peer: "chat service", call: { one: "message", many: "messages" } },
  },
];

export const CLIENT_EXPERIMENTS = EXPERIMENTS.filter((e) => !e.agentic);
export const AGENTIC_EXPERIMENTS = EXPERIMENTS.filter((e) => e.agentic);
export const isAgentic = (slug: string) => EXPERIMENTS.some((e) => e.slug === slug && e.agentic);
export const agenticInfo = (slug: string): AgenticInfo =>
  EXPERIMENTS.find((e) => e.slug === slug)?.agentic ?? { peer: "service", call: { one: "call", many: "calls" } };

/** An experiment that can be opened in the app, by slug. */
export const availableExperiment = (slug: string) => EXPERIMENTS.find((e) => e.slug === slug && e.available);

export const experimentName = (slug: string) => EXPERIMENTS.find((e) => e.slug === slug)?.name ?? slug;

/** Whether a run's prompts were written for it: always in Custom Prompts, by choice in a Custom Experiment. Its results then go prompt by prompt. */
export const hasOwnPrompts = (run: { experiment: string; config: { prompt_source?: string } }) =>
  run.config.prompt_source === "written" || (EXPERIMENTS.find((e) => e.slug === run.experiment)?.ownPrompts ?? false);

export const experimentHref = (slug: string) => `/experiments/${slug}`;
export const runHref = (run: { experiment: string; id: string }) => `/experiments/${run.experiment}/runs/${run.id}`;
