"use client";

import { useSyncExternalStore } from "react";
import { Check, Palette } from "lucide-react";

import { ACCENTS, applyAccent, currentAccent, subscribeAppearance } from "@/lib/theme";
import { Card } from "@/components/ui";
import { ThemeToggle } from "@/components/shell/ThemeToggle";

export function AppearanceCard() {
  const accent = useSyncExternalStore(subscribeAppearance, currentAccent, () => null);

  return (
    <Card
      title="Appearance"
      description="Theme and accent color. Saved in this browser."
      action={<Palette className="h-4 w-4 text-ink-3" />}
    >
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium">Theme</div>
          <div className="text-xs text-ink-3">System follows your operating system&apos;s setting.</div>
        </div>
        <ThemeToggle withLabels />
      </div>
      <div className="mb-2 text-sm font-medium">Accent color</div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {ACCENTS.map((a) => {
          const selected = accent === a.id;
          return (
            <button
              key={a.id}
              type="button"
              onClick={() => applyAccent(a.id)}
              aria-pressed={selected}
              className={`flex items-center gap-3 rounded-xl border p-3 text-left text-sm transition-all ${
                selected ? "border-accent ring-4 ring-accent/15" : "border-hairline hover:border-axis"
              }`}
            >
              <span
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full shadow-inner"
                style={{ background: `linear-gradient(135deg, ${a.swatch} 50%, ${a.swatchDark} 50%)` }}
              >
                {selected && <Check className="h-4 w-4 text-white drop-shadow" strokeWidth={3} />}
              </span>
              <span className={selected ? "font-medium" : "text-ink-2"}>{a.label}</span>
            </button>
          );
        })}
      </div>
    </Card>
  );
}
