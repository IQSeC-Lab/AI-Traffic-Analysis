"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api, type Settings } from "@/lib/api";
import { experimentHref } from "@/lib/experiments";
import { Alert, Card, Field, Spinner, buttonClass, inputClass } from "@/components/ui";

/** The sampling temperature of every experiment except Temperature Change. */
export function SamplingCard() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api<Settings>("/settings")
      .then((s) => {
        setSettings(s);
        setValue(String(s.default_temperature));
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  async function save(method: "PUT" | "DELETE") {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const s = await api<Settings>("/settings/default-temperature", {
        method,
        body: method === "PUT" ? JSON.stringify({ temperature: Number(value) }) : undefined,
      });
      setSettings(s);
      setValue(String(s.default_temperature));
      setSaved(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const number = Number(value);
  const valid = value.trim() !== "" && number >= 0 && number <= 2;
  const original = settings?.original_temperature ?? 0.7;
  const isOriginal = settings?.default_temperature === original;

  return (
    <Card
      title="Sampling"
      description="The temperature the model samples at in Data Collector, Custom Prompts, Scalability and Delay runs."
    >
      <div className="space-y-4">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (valid) save("PUT");
          }}
          className="flex flex-col gap-3 sm:flex-row sm:items-end"
        >
          <div className="w-44">
            <Field label="Default temperature" hint="From 0 to 2.">
              <input
                type="number"
                min={0}
                max={2}
                step={0.05}
                value={value}
                onChange={(e) => {
                  setValue(e.target.value);
                  setSaved(false);
                }}
                className={inputClass}
              />
            </Field>
          </div>
          <div className="flex gap-2 sm:mb-[22px]">
            <button
              type="submit"
              disabled={busy || !valid || number === settings?.default_temperature}
              className={buttonClass()}
            >
              {busy && <Spinner />} Save
            </button>
            {settings && !isOriginal && (
              <button type="button" onClick={() => save("DELETE")} disabled={busy} className={buttonClass("secondary")}>
                Use {original}
              </button>
            )}
          </div>
        </form>

        {error && <Alert>{error}</Alert>}
        {value.trim() !== "" && !valid && <p className="text-xs text-critical-text">Enter a value from 0 to 2.</p>}
        {saved && !error && <p className="text-xs text-good-text">Saved. New runs sample at {settings?.default_temperature}.</p>}

        <p className="text-xs text-ink-3">
          The original scripts sample at {original}. 0 is greedy decoding: always the most likely token. A run keeps the
          temperature it started with, so changing this only affects new runs.{" "}
          <Link href={experimentHref("temperature-change")} className="font-medium text-ink-2 underline">
            Temperature Change
          </Link>{" "}
          runs set their own temperatures and ignore this. In a Custom Experiment, each scenario starts at it and can
          be changed.
        </p>
      </div>
    </Card>
  );
}
