import {
  Database,
  Factory,
  Globe,
  Layers,
  Network,
  PenLine,
  Radar,
  SlidersHorizontal,
  Thermometer,
  Timer,
  Users,
  VenetianMask,
  Waypoints,
  type LucideIcon,
} from "lucide-react";

import { PLC_TASKS, type TaskGroup } from "./plcTasks";

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
  /** The Information page: what a run of it lets you set, beyond what every run of its group sets. */
  options?: [string, string][];
  /** The Information page: its tasks, each explained, for an experiment with a fixed set of its own. */
  tasks?: TaskGroup[];
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
    options: [
      ["Model", "One model. Nothing else changes between captures, so this is the baseline to compare the other experiments against."],
    ],
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
    options: [
      ["Temperatures", "Up to 8, from 0 to 2: pick from the list or type another value. Every prompt is captured once at each. 0 is greedy decoding, where the model always picks its most likely token."],
      ["Model", "One model, the same at every temperature."],
    ],
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
    options: [
      ["Prompts", "Written in the experiment and kept apart from the library. Edit, remove or add to the 10 LLMmap prompts it starts with. Results are shown prompt by prompt."],
      ["Model", "One model."],
      ["Repeat", "10 times each by default, as in the original experiment."],
    ],
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
    options: [
      ["Models", "Up to 8 downloaded models. Every one gets the same prompts, so the model is the only thing that changes. The form shows how much GPU memory each needs."],
      ["Prompts", "The 10 Code Generation prompts, 10 times each by default, as in the original experiment."],
    ],
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
    options: [
      ["Network conditions", "Up to 8, each a delay and a jitter in milliseconds. tc netem adds them to everything the inference server sends, the response stream included. Keep one with no delay to compare against."],
      ["Jitter shape", "How each packet's delay varies around the set value: normal, pareto or paretonormal."],
      ["Prompts", "The 10 Logical Reasoning & Puzzles prompts, 10 times each by default, as in the original experiment."],
      ["Host", "Needs the sch_netem kernel module: sudo modprobe sch_netem."],
    ],
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
    options: [
      ["Scenarios", "Up to 8. Each has its own model (Hugging Face or Ollama, tagged in the list), temperature, delay, jitter and jitter shape, and an optional label. Without a label, the results name a scenario by what sets it apart from the others."],
      ["Prompts", "From the prompt library, or written in the experiment as in Custom Prompts."],
    ],
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
    options: [
      ["Task categories", "MARBLE's bargaining, bug fix, coding, debate, deep research, legal review, medical diagnosis and SWE-bench tasks. Each task defines its own agents, usually 3 to 5. Database and Research tasks can't run here: they need docker compose or the internet."],
    ],
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
    options: [
      ["Task categories", "Lookup reads one row or a few, insert adds rows, update changes rows, delete removes them, and report reads and summarizes many rows. 15 tasks each."],
      ["Agents", "The same 3 for every task: one writes and runs the SQL, one looks up the rows the request is about, and one checks the result."],
    ],
  },
  {
    slug: "agent-to-plc",
    name: "Agent to PLC",
    summary: "Agents running a simulated plant",
    description:
      "Several agents carry out a request on a PLC that runs a small brewery (read sensors, change settings, call a method, watch the plant respond), and every request they send to it over OPC UA is captured. The PLC is simulated in a container on the run's private network and started again for every task. A run can capture each task under more than one coordination topology.",
    icon: Factory,
    available: true,
    variable: { one: "topology", many: "topologies" },
    agentic: { peer: "PLC", call: { one: "request", many: "requests" }, failed: "Refused by the PLC" },
    options: [
      ["Task categories", "Monitor, compare, explore, control, closed loop, incident, history, anomaly and setpoints, 2 tasks each (18 in all). Closed-loop tasks change a setting, keep reading until the plant has responded, then change it back."],
      ["The PLC", "Microsoft's OPC PLC simulator. It holds the brewery (three fermenters, a bottling line, the active recipe and a stacklight), loaded from a nodes file, and the simulator's own Boiler #2, whose heater has a Switch method. Sensors are read only, settings can be changed."],
      ["Physics", "Values from a nodes file never change on their own, so a small program runs beside the PLC and moves them. Once a second it reads the settings and writes the sensors: a fermenter cools 0.2 °C a second while its cooling is on and warms 0.02 °C a second while it is off, its level drops 1 % a second while its outlet valve is open, and the bottling line fills Speed ÷ 60 bottles a second while it runs. It reaches the PLC over the PLC container's own loopback, so none of its traffic is in the capture."],
      ["Starting states", "Every task starts from one of three states of the same plant, so a browse finds the same nodes in all of them. Normal: everything near its target. Fault: fermenter B too warm with its cooling off, a leak in fermenter C, and the bottling line rejecting every 5th bottle. Changeover: the line stopped, fermenter C empty, a new recipe to load."],
      ["Agents", "The same 3 for every task, with four tools: browse lists what a folder holds, read reads a value, write changes a setting, and call runs a method. One changes settings, one reads and browses, and one checks the result."],
      ["Encryption", "Every tool call is its own OPC UA connection, signed and encrypted (Basic256Sha256). The first call of a task also asks the PLC for its certificate over an unencrypted connection, as OPC UA clients do. OPC UA's own setup messages are left out of the measurements, like a TLS handshake."],
    ],
    tasks: PLC_TASKS,
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
    options: [
      ["Task categories", "Papers searches arXiv, Medical searches MedlinePlus, and Security searches the National Vulnerability Database (put the word exploited in a request to search only CISA's Known Exploited Vulnerabilities). 15 tasks each."],
      ["Agents", "The same 3 for every task, with two tools: search returns titles and addresses, and read opens one of them. One searches, one reads the best result, and one checks the answer against a second page."],
      ["Workers", "Always one, so the sites get one request at a time. What is captured depends on what the sites answer that day."],
    ],
  },
  {
    slug: "agent-to-agents",
    name: "Agent to Agents",
    summary: "Agents talking to each other",
    description:
      "Several agents work on a MARBLE task together, each in its own container, and every message they send each other is captured. They talk over A2A, the Agent2Agent protocol (JSON-RPC over HTTPS). The tasks are MARBLE's own, as in Agent to LLM, under the graph topology: every agent plans its own steps and starts its own conversations.",
    icon: Waypoints,
    available: true,
    agentic: { peer: "other agents", call: { one: "message", many: "messages" }, failed: "Not answered" },
    options: [
      ["Task categories", "MARBLE's bug fix, debate, deep research, legal review, medical diagnosis and SWE-bench tasks, 15 each, the same files Agent to LLM runs. Each task defines its own agents, 3 or 4. Bargaining and coding can't run here: their agents share one world or one workspace, which agents in separate containers don't have."],
      ["Topology", "Graph only. Every agent plans its own next step and starts its own conversations, so nothing sits between them. Under star, MARBLE's planner hands out the work, and the planner is not an agent."],
      ["Agents", "Each runs in its own container and answers the others on port 8443. A conversation is MARBLE's: one agent sends a message, the other answers with its own model call, and they take turns until one ends it or five turns have passed. The agents work as a team: each is told to always message a teammate, to share what it found or ask for their part, since a 3B model mostly answered alone in the published dataset. Both agents of a conversation remember it, so they build on what their teammates said (in MARBLE only the one that started it does). Up to 3 rounds."],
      ["Capture", "One tcpdump sidecar per agent keeps the connections that agent answers, and the sidecars' captures are merged into one PCAP per task. Every message is its own TLS connection. The agents' calls to the model, and the engine asking each agent to plan or act, are left out."],
    ],
  },
  {
    slug: "good-agent-bad-agent",
    name: "Good Agent Bad Agent",
    summary: "A team with a saboteur in it",
    description:
      "A team of agents works on a MARBLE task, each in its own container as in Agent to Agents, and some of them are secretly working against the others. Good and bad agents differ only in the prompt they start with, which no other agent sees. Every message they send each other is captured.",
    icon: VenetianMask,
    available: true,
    variable: { one: "lineup", many: "lineups" },
    agentic: { peer: "other agents", call: { one: "message", many: "messages" }, failed: "Not answered" },
    options: [
      ["Team", "How many good and how many bad agents, up to 8 in all. They take the task's roles in turn. Which agents are bad is drawn again for every task and repetition, so being bad is not tied to an agent's name or role."],
      ["Models", "One model, called by every agent, or several. With several, the agents take them in turn and every task is captured once per lineup, each model taking its turn as the bad one, so a difference between good and bad is not a difference between models."],
      ["Control", "On by default: every task is also captured with every agent good, the same agents and models, to compare against."],
      ["Starting prompts", "What a good agent and what a bad agent is told, after its role in the task. Each agent gets its own in its own container. By default a bad agent keeps messaging and looks helpful while giving plausible wrong facts, flawed code or bad advice."],
      ["Task categories", "The same as Agent to Agents: MARBLE's bug fix, debate, deep research, legal review, medical diagnosis and SWE-bench tasks, 15 each, under the graph topology."],
    ],
  },
  // Not in the app yet
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

/** What a run of the experiment compares, in lowercase: "topology" for the agentic ones that don't say. */
export const variableOf = (slug: string) => EXPERIMENTS.find((e) => e.slug === slug)?.variable ?? { one: "topology", many: "topologies" };

export const experimentName = (slug: string) => EXPERIMENTS.find((e) => e.slug === slug)?.name ?? slug;

/** Whether a run's prompts were written for it: always in Custom Prompts, by choice in a Custom Experiment. Its results then go prompt by prompt. */
export const hasOwnPrompts = (run: { experiment: string; config: { prompt_source?: string } }) =>
  run.config.prompt_source === "written" || (EXPERIMENTS.find((e) => e.slug === run.experiment)?.ownPrompts ?? false);

export const experimentHref = (slug: string) => `/experiments/${slug}`;
export const runHref = (run: { experiment: string; id: string }) => `/experiments/${run.experiment}/runs/${run.id}`;
