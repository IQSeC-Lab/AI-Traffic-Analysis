"use client";

import Link from "next/link";
import { X } from "lucide-react";

import { DISTRIBUTIONS, modelRef, type LocalModel, type NetworkCondition, type Scenario } from "@/lib/api";
import { MAX_VARIANTS } from "@/lib/experiments";
import { conditionLabel } from "@/lib/format";
import { Alert, ButtonLink, buttonClass, inputClass } from "@/components/ui";
import { Section } from "./FormSection";
import { modelName, variantColor } from "./RunBadge";

/** A scenario while it is being edited: the temperature as typed, and an empty label until one is written. */
export type ScenarioDraft = { model: string; temperature: string; network: NetworkCondition; label: string };

export const newScenario = (model: string, temperature: number): ScenarioDraft => ({
  model,
  temperature: String(temperature),
  network: { delay_ms: 0, jitter_ms: 0, distribution: "normal" },
  label: "",
});

// To two decimals, as the API rounds it. NaN while the field is empty.
const temperatureOf = (s: ScenarioDraft) => (s.temperature.trim() === "" ? NaN : Math.round(Number(s.temperature) * 100) / 100);

const milliseconds = (value: string) => Math.min(10000, Math.max(0, Math.round(Number(value) || 0)));

/** The scenario as the API takes it. */
export const toScenario = (s: ScenarioDraft): Scenario => ({
  model: s.model,
  temperature: temperatureOf(s),
  network: s.network,
  label: s.label.trim() || null,
});

/**
 * How the results name each scenario, as the API does: its own label, or what sets it apart
 * from the others (model, temperature, network condition). A scenario on its own is named by all three.
 */
export function scenarioLabels(scenarios: ScenarioDraft[]): string[] {
  const models = scenarios.map((s) => s.model);
  const short = models.map(modelName);
  const temperatures = scenarios.map((s) => (Number.isNaN(temperatureOf(s)) ? "?" : `${temperatureOf(s)}`));
  const parts = [
    new Set(short).size < new Set(models).size ? models : short, // the same model name from two organizations
    temperatures,
    scenarios.map((s) => conditionLabel(s.network)),
  ];
  const differing = parts.some((p) => new Set(p).size > 1) ? parts.filter((p) => new Set(p).size > 1) : parts;
  // Charts have little room for a label: the temperature is only spelled out when it is all there is
  const temperature = differing.length > 1 ? "T" : "Temperature";
  const names = differing.map((p) => (p === temperatures ? p.map((t) => `${temperature} ${t}`) : p));
  return scenarios.map((s, i) => s.label.trim() || names.map((p) => p[i]).join(" · "));
}

/** Why a scenario can't run, if it can't: a setting is missing or out of range, or it repeats an earlier one. */
export function scenarioProblem(scenarios: ScenarioDraft[], i: number): string | null {
  const s = scenarios[i];
  if (!s.model) return "Pick a model.";
  const t = temperatureOf(s);
  if (!(t >= 0 && t <= 2)) return "The temperature goes from 0 to 2.";
  if (s.network.jitter_ms && !s.network.delay_ms) return "Jitter needs a delay.";
  const settings = (x: ScenarioDraft) => [x.model, temperatureOf(x), conditionLabel(x.network)].join(" ");
  const same = scenarios.findIndex((o) => settings(o) === settings(s));
  if (same < i) return `Same as scenario ${same + 1}.`;
  const labels = scenarioLabels(scenarios);
  const named = labels.indexOf(labels[i]);
  return named < i ? `Same label as scenario ${named + 1}.` : null;
}

const COLUMNS = "grid grid-cols-[1.25rem_minmax(0,1fr)_5.5rem_5rem_5rem_8rem_2rem] gap-3";

/** The scenarios of a Custom Experiment run: one row each, with everything the other experiments set. */
export function ScenariosEditor({
  scenarios,
  onChange,
  models,
}: {
  scenarios: ScenarioDraft[];
  onChange: (scenarios: ScenarioDraft[]) => void;
  models: LocalModel[];
}) {
  const labels = scenarioLabels(scenarios);
  const update = (i: number, change: Partial<ScenarioDraft>) => onChange(scenarios.map((s, j) => (j === i ? { ...s, ...change } : s)));
  const updateNetwork = (i: number, change: Partial<NetworkCondition>) => update(i, { network: { ...scenarios[i].network, ...change } });

  return (
    <Section
      title="Scenarios"
      description={`What the run compares. Each scenario has its own model, sampling temperature and network condition, and every prompt is captured once in each. Up to ${MAX_VARIANTS}.`}
      action={
        <div className="flex gap-1">
          <ButtonLink href="/settings#models" variant="secondary" size="sm">
            Download more
          </ButtonLink>
          <button
            type="button"
            disabled={scenarios.length >= MAX_VARIANTS || models.length === 0}
            // Starts as a copy of the last one, so only what differs has to be changed
            onClick={() => onChange([...scenarios, { ...scenarios[scenarios.length - 1], label: "" }])}
            className={buttonClass("secondary", "sm")}
          >
            Add scenario
          </button>
        </div>
      }
    >
      {models.length === 0 ? (
        <Alert tone="warning">
          No models downloaded yet.{" "}
          <Link href="/settings#models" className="font-medium text-ink underline">
            Download one in Settings
          </Link>
          .
        </Alert>
      ) : (
        <>
          <div className="space-y-2">
            <div className={`${COLUMNS} px-3 text-xs font-medium text-ink-3`}>
              <span />
              <span>Model</span>
              <span>Temperature</span>
              <span>Delay (ms)</span>
              <span>Jitter (ms)</span>
              <span>Jitter shape</span>
              <span />
            </div>
            {scenarios.map((s, i) => {
              const problem = scenarioProblem(scenarios, i);
              return (
                <div key={i} className="rounded-xl border border-hairline px-3 py-2.5">
                  <div className={`${COLUMNS} items-center`}>
                    <span className="flex justify-center">
                      <span className="h-2 w-2 rounded-full" style={{ background: variantColor(i) }} />
                    </span>
                    <select
                      value={s.model}
                      onChange={(e) => update(i, { model: e.target.value })}
                      className={inputClass}
                      aria-label={`Model of scenario ${i + 1}`}
                    >
                      {models.map((m) => (
                        <option key={m.folder} value={modelRef(m)}>
                          {modelName(modelRef(m))}
                        </option>
                      ))}
                    </select>
                    <input
                      type="number"
                      min={0}
                      max={2}
                      step={0.05}
                      value={s.temperature}
                      onChange={(e) => update(i, { temperature: e.target.value })}
                      className={inputClass}
                      aria-label={`Temperature of scenario ${i + 1}, 0 to 2`}
                    />
                    <input
                      type="number"
                      min={0}
                      max={10000}
                      value={s.network.delay_ms}
                      onChange={(e) => updateNetwork(i, { delay_ms: milliseconds(e.target.value) })}
                      className={inputClass}
                      aria-label={`Delay of scenario ${i + 1}, in milliseconds`}
                    />
                    <input
                      type="number"
                      min={0}
                      max={10000}
                      value={s.network.jitter_ms}
                      onChange={(e) => updateNetwork(i, { jitter_ms: milliseconds(e.target.value) })}
                      className={inputClass}
                      aria-label={`Jitter of scenario ${i + 1}, in milliseconds`}
                    />
                    <select
                      value={s.network.distribution}
                      disabled={!s.network.jitter_ms}
                      onChange={(e) => updateNetwork(i, { distribution: e.target.value as NetworkCondition["distribution"] })}
                      className={`${inputClass} disabled:text-ink-3`}
                      aria-label={`Jitter distribution of scenario ${i + 1}`}
                    >
                      {DISTRIBUTIONS.map((d) => (
                        <option key={d} value={d}>
                          {d}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => onChange(scenarios.filter((_, j) => j !== i))}
                      disabled={scenarios.length === 1}
                      className="flex h-8 w-8 items-center justify-center rounded-lg text-ink-3 hover:bg-surface-2 hover:text-critical-text disabled:invisible"
                      aria-label={`Remove scenario ${i + 1}`}
                      title="Remove"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                  {/* Indented past the color dot, under the model */}
                  <div className="mt-2 flex items-center gap-3 pr-11 pl-8">
                    <label className="flex min-w-0 flex-1 items-center gap-2 text-xs font-medium text-ink-3">
                      Label
                      <input
                        value={s.label}
                        maxLength={60}
                        onChange={(e) => update(i, { label: e.target.value })}
                        placeholder={labels[i]}
                        className={`${inputClass} font-normal`}
                      />
                    </label>
                    {problem && <span className="shrink-0 text-xs text-critical-text">{problem}</span>}
                  </div>
                </div>
              );
            })}
          </div>
          <p className="mt-3 text-xs text-ink-3">
            Without a label, the results name a scenario by what sets it apart from the others. Temperature 0 is greedy
            decoding. Delay and jitter are added with tc netem to everything the inference server sends, and 0 leaves
            the network as it is. A delay needs the host kernel&apos;s sch_netem module (
            <code className="text-ink-2">sudo modprobe sch_netem</code>).
          </p>
        </>
      )}
    </Section>
  );
}
