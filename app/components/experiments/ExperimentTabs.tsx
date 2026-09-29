"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { List, Plus } from "lucide-react";

export function ExperimentTabs({ base }: { base: string }) {
  const pathname = usePathname();
  const tabs = [
    { href: base, label: "Runs", icon: List },
    { href: `${base}/new`, label: "New run", icon: Plus },
  ];
  return (
    <div className="mb-8 flex gap-1 border-b border-hairline">
      {tabs.map(({ href, label, icon: Icon }) => {
        const active = pathname === href;
        return (
          <Link
            key={href}
            href={href}
            className={`-mb-px inline-flex items-center gap-2 border-b-2 px-3 pb-2.5 text-sm transition-colors ${
              active ? "border-accent font-medium text-ink" : "border-transparent text-ink-3 hover:text-ink"
            }`}
          >
            <Icon className="h-4 w-4" strokeWidth={1.75} />
            {label}
          </Link>
        );
      })}
    </div>
  );
}
