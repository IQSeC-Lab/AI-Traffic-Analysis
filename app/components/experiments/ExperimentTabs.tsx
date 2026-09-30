"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export function ExperimentTabs({ base }: { base: string }) {
  const pathname = usePathname();
  const tabs = [
    { href: base, label: "Runs" },
    { href: `${base}/new`, label: "New run" },
  ];
  return (
    <div className="mb-8 flex gap-1 border-b border-hairline">
      {tabs.map(({ href, label }) => {
        const active = pathname === href;
        return (
          <Link
            key={href}
            href={href}
            className={`-mb-px inline-flex items-center gap-2 border-b-2 px-3 pb-2.5 text-sm transition-colors ${
              active ? "border-accent font-medium text-ink" : "border-transparent text-ink-3 hover:text-ink"
            }`}
          >
            {label}
          </Link>
        );
      })}
    </div>
  );
}
