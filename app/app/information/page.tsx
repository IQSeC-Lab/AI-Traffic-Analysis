import type { Metadata } from "next";
import Link from "next/link";

import { AGENTIC_EXPERIMENTS, CLIENT_EXPERIMENTS, MAX_VARIANTS, experimentHref } from "@/lib/experiments";
import type { TaskGroup } from "@/lib/plcTasks";
import { Card, PageHeader } from "@/components/ui";

export const metadata: Metadata = { title: "Getting started" };

const BASICS: [string, string][] = [
  ["Capture", "One PCAP file: one prompt and its streamed response, or one task worked on by several agents."],
  ["Run", "Every capture of one New run form. Runs wait in a queue when the GPUs have no room, and Docker is cleaned up when one ends."],
  ["Variant", `What a run compares: temperatures, models, network conditions, scenarios or topologies, up to ${MAX_VARIANTS}. Every prompt or task is captured once under each, so the results show what changed.`],
];

const CLIENT_SHARED: [string, string][] = [
  ["Provider", "Hugging Face loads the models on the app's own server with transformers, as in the original experiments. Ollama serves Ollama models instead, with the same prompts, network and capture. The Custom Experiment sets it per scenario, with the model, so one run can compare the two."],
  ["Prompts", "Picked from the library by category or one by one: 60 built in (summarization, code generation, math, malware and adversarial, logic puzzles, technical explanation) plus your own from the Prompts page."],
  ["Repeat each prompt", "Every repetition gets a fresh container and its own PCAP."],
  ["Max tokens", "The most tokens the model generates for one prompt. 2048 by default."],
  ["Temperature", "Where a run doesn't vary it, the default set in Settings."],
  ["Hardware", "Auto spreads the workers over GPUs with free memory, and the run waits in the queue if none has room. Choose GPUs runs one copy of the model per GPU, or splits one copy across them when it doesn't fit on one. CPU runs go one at a time."],
  ["Workers", "Copies of the model, each with its own containers, network and capture, that divide the captures between them. More finish sooner, but workers sharing a GPU slow each other down and change the timings you capture."],
  ["Name", "Optional. Every run also gets a number, and you can rename it later."],
];

const AGENTIC_SHARED: [string, string][] = [
  ["Model", "One Ollama model, downloaded in Settings. Every agent calls the same one."],
  ["Topologies", "How MARBLE coordinates the agents. Graph gives every agent the whole task, and each decides its next step and messages the agents it is linked to. Star has one planner split the task, hand each agent its part every round and gather the results. Every task is captured once under each topology picked."],
  ["Tasks per category", "Runs tasks 1 to n of every category picked."],
  ["Repeat each task", "Every repetition runs the task again and is its own capture."],
  ["Hardware", "Where Ollama runs the model: auto, chosen GPUs or CPU. The agents themselves need no GPU."],
  ["Workers", "Each has its own Ollama, network and capture, and the tasks are divided between them."],
  ["Name", "Optional. Every run also gets a number, and you can rename it later."],
];

const GROUPS = [
  ["SI Traffic Analysis", "One prompt and its streamed response: the five RogueAgent experiments, and one you set up yourself.", CLIENT_EXPERIMENTS, CLIENT_SHARED],
  ["Agentic SI Analysis", "Several agents working on a task: one experiment per kind of communication captured, each with the coordination topology as an option.", AGENTIC_EXPERIMENTS, AGENTIC_SHARED],
] as const;

function Terms({ items, className = "" }: { items: readonly (readonly [string, string])[]; className?: string }) {
  return (
    <dl className={`grid grid-cols-[10rem_1fr] gap-x-6 gap-y-2 text-sm ${className}`}>
      {items.map(([term, text]) => (
        <div key={term} className="contents">
          <dt className="font-medium text-ink">{term}</dt>
          <dd className="text-ink-2">{text}</dd>
        </div>
      ))}
    </dl>
  );
}

// Under the experiment's row, in line with its description, and outside its link so the text can be selected
function Tasks({ groups }: { groups: readonly TaskGroup[] }) {
  const count = groups.reduce((n, g) => n + g.tasks.length, 0);
  return (
    <section className="pb-5 pl-[14.75rem] pr-[8.75rem]">
      <h3 className="text-sm font-semibold">The {count} tasks</h3>
      <p className="mt-1 text-sm text-ink-2">
        Each request is what the agents are asked, after the PLC&apos;s list of nodes (explore tasks get only the brewery&apos;s
        folder). The PLC starts the task in the state shown.
      </p>
      <div className="mt-3 divide-y divide-[var(--hairline)] border-y border-hairline">
        {groups.map((group) => (
          <div key={group.category} className="grid grid-cols-[10rem_1fr] gap-x-6 py-3">
            <div>
              <div className="text-sm font-medium text-ink">{group.category}</div>
              <div className="text-xs text-ink-3">{group.about}</div>
            </div>
            <ol className="space-y-3">
              {group.tasks.map((task, n) => (
                <li key={task.request} className="text-sm">
                  <p className="text-ink">{task.request}</p>
                  <p className="mt-0.5 text-xs text-ink-3">
                    Task {n + 1} · starts {task.state.toLowerCase()} · tools: {task.tools}
                  </p>
                  <p className="mt-1 text-ink-2">{task.explanation}</p>
                </li>
              ))}
            </ol>
          </div>
        ))}
      </div>
    </section>
  );
}

export default function InformationPage() {
  return (
    <>
      <PageHeader title="Getting started" description="What each experiment captures, and what every option of its New run form does." />
      <div className="space-y-8">
        <Card title="How a run works">
          <Terms items={BASICS} />
        </Card>

        {GROUPS.map(([title, text, experiments, shared]) => (
          <Card key={title} title={title} description={text} padded={false}>
            <ul className="divide-y divide-[var(--hairline)] border-t border-hairline">
              {experiments.map(({ slug, name, summary, description, available, options, tasks }) => {
                const body = (
                  <>
                    <div className="w-48 shrink-0">
                      <div className="text-sm font-medium">{name}</div>
                      <div className="text-xs text-ink-3">{summary}</div>
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-ink-2">{description}</p>
                      {options && <Terms items={options} className="mt-3" />}
                    </div>
                    <span className={`w-24 shrink-0 text-right text-xs ${available ? "font-medium text-accent" : "text-ink-3"}`}>
                      {available ? "Open" : "Not yet"}
                    </span>
                  </>
                );
                return (
                  <li key={slug}>
                    {available ? (
                      <Link href={experimentHref(slug)} className="flex items-start gap-6 px-5 py-4 hover:bg-surface-2/60">
                        {body}
                      </Link>
                    ) : (
                      <div className="flex items-start gap-6 px-5 py-4">{body}</div>
                    )}
                    {tasks && <Tasks groups={tasks} />}
                  </li>
                );
              })}
            </ul>
            <div className="border-t border-hairline px-5 py-4">
              <h3 className="mb-3 text-sm font-semibold">Every {title} run also sets</h3>
              <Terms items={shared} />
            </div>
          </Card>
        ))}
      </div>
    </>
  );
}
