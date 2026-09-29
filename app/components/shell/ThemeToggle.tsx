"use client";

import { useSyncExternalStore } from "react";
import { Monitor, Moon, Sun } from "lucide-react";

import { applyTheme, currentThemePref, subscribeAppearance, type ThemePref } from "@/lib/theme";

const OPTIONS: { value: ThemePref; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

/** Light / Dark / System switch. `withLabels` shows the names next to the icons. */
export function ThemeToggle({ withLabels = false }: { withLabels?: boolean }) {
  const pref = useSyncExternalStore(subscribeAppearance, currentThemePref, () => null);
  return (
    <div role="radiogroup" aria-label="Theme" className="inline-flex rounded-lg bg-surface-2 p-0.5">
      {OPTIONS.map(({ value, label, icon: Icon }) => {
        const selected = pref === value;
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-label={label}
            title={label}
            onClick={() => applyTheme(value)}
            className={`inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium transition-colors ${
              selected ? "bg-surface text-ink shadow-sm" : "text-ink-3 hover:text-ink"
            } ${withLabels ? "px-3 py-1.5" : ""}`}
          >
            <Icon className="h-3.5 w-3.5" strokeWidth={2} />
            {withLabels && label}
          </button>
        );
      })}
    </div>
  );
}
