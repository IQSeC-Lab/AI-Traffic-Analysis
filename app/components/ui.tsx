import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  CircleDashed,
  Loader2,
  XCircle,
  type LucideIcon,
} from "lucide-react";

// ── Layout ───────────────────────────────────────────────────────────────────

export function PageHeader({
  title,
  description,
  icon: Icon,
  actions,
  eyebrow,
}: {
  title: ReactNode;
  description?: ReactNode;
  icon?: LucideIcon;
  actions?: ReactNode;
  eyebrow?: ReactNode;
}) {
  return (
    <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
      <div className="flex min-w-0 items-start gap-4">
        {Icon && (
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-accent-wash text-accent ring-1 ring-inset ring-[var(--border)]">
            <Icon className="h-6 w-6" strokeWidth={1.75} />
          </div>
        )}
        <div className="min-w-0">
          {eyebrow && <div className="mb-1 text-xs font-medium text-ink-3">{eyebrow}</div>}
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {description && <p className="mt-1 max-w-2xl text-sm text-ink-2">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Card({
  title,
  description,
  action,
  children,
  id,
  className = "",
  padded = true,
}: {
  title?: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  id?: string;
  className?: string;
  padded?: boolean;
}) {
  return (
    <section
      id={id}
      className={`scroll-mt-6 rounded-2xl border border-hairline bg-surface shadow-[0_1px_2px_rgba(0,0,0,0.04)] ${className}`}
    >
      {(title || action) && (
        <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-5">
          <div>
            {title && <h2 className="text-sm font-semibold">{title}</h2>}
            {description && <p className="mt-0.5 text-sm text-ink-3">{description}</p>}
          </div>
          {action}
        </div>
      )}
      <div className={padded ? "p-5" : ""}>{children}</div>
    </section>
  );
}

// ── Controls ─────────────────────────────────────────────────────────────────

const buttonStyles = {
  primary: "bg-accent-strong text-white hover:bg-accent-strong-hover shadow-sm",
  secondary: "border border-hairline bg-surface text-ink hover:bg-surface-2",
  ghost: "text-ink-2 hover:bg-surface-2 hover:text-ink",
  danger: "bg-critical text-white hover:opacity-90 shadow-sm",
};

export function buttonClass(variant: keyof typeof buttonStyles = "primary", size: "sm" | "md" = "md") {
  const sizes = size === "sm" ? "h-8 px-3 text-xs" : "h-9 px-4 text-sm";
  return `inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 ${sizes} ${buttonStyles[variant]}`;
}

export function ButtonLink({
  variant = "primary",
  size = "md",
  className = "",
  ...props
}: ComponentProps<typeof Link> & { variant?: keyof typeof buttonStyles; size?: "sm" | "md" }) {
  return <Link {...props} className={`${buttonClass(variant, size)} ${className}`} />;
}

export const inputClass =
  "h-9 w-full rounded-lg border border-hairline bg-surface px-3 text-sm outline-none transition-shadow placeholder:text-ink-3 focus:border-accent focus:ring-4 focus:ring-accent/15";

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium">{label}</span>
      {children}
      {hint && <span className="mt-1.5 block text-xs text-ink-3">{hint}</span>}
    </label>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div className="inline-flex rounded-lg bg-surface-2 p-0.5 text-xs">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={`rounded-md px-2.5 py-1 font-medium transition-colors ${
            o.value === value ? "bg-surface text-ink shadow-sm" : "text-ink-3 hover:text-ink"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

// ── Data display ─────────────────────────────────────────────────────────────

export function StatTile({
  label,
  value,
  hint,
  icon: Icon,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  icon?: LucideIcon;
}) {
  return (
    <div className="rounded-2xl border border-hairline bg-surface p-4 shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-ink-3">{label}</span>
        {Icon && <Icon className="h-4 w-4 text-ink-3" strokeWidth={1.75} />}
      </div>
      <div className="mt-2 text-2xl font-semibold tracking-tight">{value}</div>
      {hint && <div className="mt-1 text-xs text-ink-3">{hint}</div>}
    </div>
  );
}

export function ProgressBar({ value, max, tone = "accent" }: { value: number; max: number; tone?: "accent" | "good" }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-accent-wash">
      <div
        className={`h-full rounded-full transition-[width] duration-500 ${tone === "good" ? "bg-good" : "bg-accent"}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

const STATUS: Record<string, { label: string; icon: LucideIcon | "live"; color: string }> = {
  pending: { label: "Starting", icon: "live", color: "var(--accent)" },
  running: { label: "Running", icon: "live", color: "var(--accent)" },
  cancelling: { label: "Cancelling", icon: Loader2, color: "var(--warning)" },
  cleaning_up: { label: "Cleaning up", icon: Loader2, color: "var(--warning)" },
  completed: { label: "Completed", icon: CheckCircle2, color: "var(--good)" },
  failed: { label: "Failed", icon: XCircle, color: "var(--critical)" },
  cancelled: { label: "Cancelled", icon: Ban, color: "var(--ink-3)" },
  interrupted: { label: "Interrupted", icon: AlertTriangle, color: "var(--serious)" },
  queued: { label: "Queued", icon: CircleDashed, color: "var(--ink-3)" },
  preparing: { label: "Preparing", icon: Loader2, color: "var(--accent)" },
  downloading: { label: "Downloading", icon: "live", color: "var(--accent)" },
};

export function LiveDot({ color = "var(--accent)" }: { color?: string }) {
  return (
    <span className="relative inline-flex h-2 w-2">
      <span
        className="absolute inline-flex h-full w-full rounded-full"
        style={{ background: color, animation: "live-ping 1.6s cubic-bezier(0,0,0.2,1) infinite" }}
      />
      <span className="relative inline-flex h-2 w-2 rounded-full" style={{ background: color }} />
    </span>
  );
}

/** Status is carried by icon + label, never color alone. */
export function StatusPill({ status }: { status: string }) {
  const s = STATUS[status] ?? { label: status, icon: CircleDashed, color: "var(--ink-3)" };
  const Icon = s.icon;
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-hairline bg-surface px-2 py-0.5 text-xs font-medium text-ink-2">
      {Icon === "live" ? (
        <LiveDot color={s.color} />
      ) : (
        <Icon
          className={`h-3.5 w-3.5 ${Icon === Loader2 ? "animate-spin" : ""}`}
          style={{ color: s.color }}
          strokeWidth={2}
        />
      )}
      {s.label}
    </span>
  );
}

export function Alert({
  tone = "critical",
  children,
}: {
  tone?: "critical" | "warning" | "info";
  children: ReactNode;
}) {
  const tones = {
    critical: { icon: XCircle, color: "var(--critical)" },
    warning: { icon: AlertTriangle, color: "var(--serious)" },
    info: { icon: CircleDashed, color: "var(--accent)" },
  };
  const { icon: Icon, color } = tones[tone];
  return (
    <div className="flex gap-2.5 rounded-xl border border-hairline bg-surface-2 px-3.5 py-3 text-sm text-ink-2">
      <Icon className="mt-0.5 h-4 w-4 shrink-0" style={{ color }} strokeWidth={2} />
      <div className="min-w-0">{children}</div>
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  children,
  action,
}: {
  icon: LucideIcon;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center rounded-2xl border border-dashed border-hairline px-6 py-14 text-center">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-accent-wash text-accent">
        <Icon className="h-6 w-6" strokeWidth={1.75} />
      </div>
      <h3 className="text-sm font-semibold">{title}</h3>
      {children && <p className="mt-1 max-w-sm text-sm text-ink-3">{children}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return <Loader2 className={`animate-spin ${className}`} strokeWidth={2} />;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-10 text-sm text-ink-3">
      <Spinner /> {label}
    </div>
  );
}
