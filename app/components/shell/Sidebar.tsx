"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Cpu, LayoutDashboard, Menu, MessagesSquare, Radar, Settings, X } from "lucide-react";

import { api, type Run, type SystemInfo } from "@/lib/api";
import { EXPERIMENTS, ORCHESTRATOR_EXPERIMENTS, experimentHref, runHref } from "@/lib/experiments";
import { useInterval } from "@/lib/useInterval";
import { LiveDot } from "@/components/ui";
import { RunBadge, runTitle } from "@/components/experiments/RunBadge";
import { ThemeToggle } from "./ThemeToggle";

function NavItem({
  href,
  icon: Icon,
  label,
  active,
  disabled,
  trailing,
}: {
  href: string;
  icon: typeof Radar;
  label: string;
  active: boolean;
  disabled?: boolean;
  trailing?: React.ReactNode;
}) {
  const classes = `group flex h-9 items-center gap-2.5 rounded-lg px-2.5 text-sm transition-colors ${
    active
      ? "bg-surface text-ink font-medium shadow-[0_1px_2px_rgba(0,0,0,0.06)] ring-1 ring-[var(--border)]"
      : disabled
        ? "text-ink-3 cursor-default"
        : "text-ink-2 hover:bg-surface/70 hover:text-ink"
  }`;
  const content = (
    <>
      <Icon className={`h-4 w-4 shrink-0 ${active ? "text-accent" : ""}`} strokeWidth={1.75} />
      <span className="flex-1 truncate">{label}</span>
      {trailing}
    </>
  );
  return disabled ? (
    <div className={classes} aria-disabled>
      {content}
    </div>
  ) : (
    <Link href={href} className={classes}>
      {content}
    </Link>
  );
}

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const [active, setActive] = useState<Run[]>([]);
  const [system, setSystem] = useState<SystemInfo | null>(null);

  const refresh = useCallback(() => {
    api<Run[]>("/experiments/active").then(setActive).catch(() => {});
  }, []);
  useEffect(refresh, [refresh, pathname]);
  useInterval(refresh, 4000);
  useEffect(() => {
    api<SystemInfo>("/system").then(setSystem).catch(() => {});
  }, []);

  return (
    <div className="flex min-h-full flex-col gap-6 px-3 py-4" onClick={(e) => (e.target as HTMLElement).closest("a") && onNavigate?.()}>
      <Link href="/" className="flex items-center gap-2.5 px-2">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-strong text-white">
          <Radar className="h-4.5 w-4.5" strokeWidth={2} />
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold tracking-tight">RogueAgent</div>
          <div className="text-[11px] text-ink-3">LLM traffic fingerprinting</div>
        </div>
      </Link>

      <nav className="space-y-0.5">
        <NavItem href="/" icon={LayoutDashboard} label="Overview" active={pathname === "/"} />
      </nav>

      <nav className="space-y-0.5">
        <div className="px-2.5 pb-1.5 text-[11px] font-medium tracking-wide text-ink-3 uppercase">Client to Server</div>
        {EXPERIMENTS.map((e) => {
          const href = experimentHref(e.slug);
          const running = active.some((r) => r.experiment === e.slug && r.status !== "queued");
          return (
            <NavItem
              key={e.slug}
              href={href}
              icon={e.icon}
              label={e.name}
              active={pathname.startsWith(href)}
              disabled={!e.available}
              trailing={
                running ? (
                  <LiveDot />
                ) : !e.available ? (
                  <span className="rounded-md bg-surface-2 px-1.5 py-0.5 text-[10px] font-medium text-ink-3">Soon</span>
                ) : null
              }
            />
          );
        })}
      </nav>

      <nav className="space-y-0.5">
        <div className="px-2.5 pb-1.5 text-[11px] font-medium tracking-wide text-ink-3 uppercase">Agentic Orchestrator</div>
        {ORCHESTRATOR_EXPERIMENTS.map((e) => (
          <NavItem
            key={e.slug}
            href={experimentHref(e.slug)}
            icon={e.icon}
            label={e.name}
            active={false}
            disabled={!e.available}
            trailing={
              !e.available && <span className="rounded-md bg-surface-2 px-1.5 py-0.5 text-[10px] font-medium text-ink-3">Soon</span>
            }
          />
        ))}
      </nav>

      <nav className="space-y-0.5">
        <div className="px-2.5 pb-1.5 text-[11px] font-medium tracking-wide text-ink-3 uppercase">Library</div>
        <NavItem href="/prompts" icon={MessagesSquare} label="Prompts" active={pathname.startsWith("/prompts")} />
      </nav>

      <div className="mt-auto space-y-3">
        {active.length > 0 && (
          <div className="rounded-xl border border-hairline bg-surface p-1.5 shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
            <div className="flex items-center justify-between px-1.5 pt-1 pb-1.5 text-xs font-medium">
              <span className="flex items-center gap-2">
                <LiveDot /> {active.filter((r) => r.status !== "queued").length} running
              </span>
              {active.some((r) => r.status === "queued") && (
                <span className="text-ink-3">{active.filter((r) => r.status === "queued").length} queued</span>
              )}
            </div>
            {active.slice(0, 4).map((run) => (
              <Link key={run.id} href={runHref(run)} className="block rounded-lg px-1.5 py-1.5 hover:bg-surface-2">
                <div className="flex items-center justify-between gap-2 text-[11px]">
                  <span className="flex min-w-0 items-center gap-1.5">
                    <RunBadge number={run.number} />
                    <span className="truncate text-ink-2">{runTitle(run)}</span>
                  </span>
                  <span className="shrink-0 text-ink-3 tabular-nums">
                    {run.status === "queued" ? `#${run.queue?.position ?? "–"} in queue` : `${run.progress.completed}/${run.progress.total}`}
                  </span>
                </div>
                <div className="mt-1 h-1 overflow-hidden rounded-full bg-accent-wash">
                  <div
                    className="h-full rounded-full bg-accent transition-[width] duration-500"
                    style={{ width: `${(run.progress.completed / Math.max(1, run.progress.total)) * 100}%` }}
                  />
                </div>
              </Link>
            ))}
            {active.length > 4 && <div className="px-1.5 pb-1 text-[11px] text-ink-3">+{active.length - 4} more</div>}
          </div>
        )}

        <nav className="space-y-0.5">
          <NavItem href="/settings" icon={Settings} label="Settings" active={pathname.startsWith("/settings")} />
        </nav>

        <div className="flex items-center justify-between gap-2 px-2.5">
          <span className="text-xs text-ink-3">Theme</span>
          <ThemeToggle />
        </div>

        {system && (
          <div className="flex items-center gap-2 px-2.5 text-[11px] text-ink-3">
            <span
              className="h-1.5 w-1.5 rounded-full"
              style={{ background: system.docker.available ? "var(--good)" : "var(--critical)" }}
            />
            Docker {system.docker.available ? system.docker.version : "offline"}
            <span className="text-hairline">·</span>
            <Cpu className="h-3 w-3" />
            {system.gpus.length > 0 ? `${system.gpus.length} GPU${system.gpus.length > 1 ? "s" : ""}` : "CPU only"}
          </div>
        )}
      </div>
    </div>
  );
}

export function Sidebar() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 overflow-y-auto border-r border-hairline bg-page lg:block">
        <SidebarContent />
      </aside>

      {/* Mobile */}
      <div className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-hairline bg-page px-4 lg:hidden">
        <Link href="/" className="flex items-center gap-2 text-sm font-semibold">
          <Radar className="h-4 w-4 text-accent" /> RogueAgent
        </Link>
        <button type="button" onClick={() => setOpen(true)} className="rounded-lg p-2 hover:bg-surface-2" aria-label="Open menu">
          <Menu className="h-5 w-5" />
        </button>
      </div>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/30" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 overflow-y-auto border-r border-hairline bg-page shadow-xl">
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="absolute top-4 right-3 rounded-lg p-1.5 hover:bg-surface-2"
              aria-label="Close menu"
            >
              <X className="h-4 w-4" />
            </button>
            <SidebarContent onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      )}
    </>
  );
}
